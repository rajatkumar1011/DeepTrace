"use client";

/**
 * Record a reference voice sample in the browser.
 *
 * MediaRecorder produces WebM/Opus in Chromium and Ogg/Opus in Firefox. Neither is
 * accepted by the enrollment endpoint, which gates on AUDIO_EXTENSIONS
 * ({.wav,.mp3,.flac,.ogg,.m4a}) and where `.webm` is classified as *video*. The
 * recording is therefore decoded and re-encoded here as 16-bit PCM WAV, which is
 * both accepted by the API and directly readable by the SpeechBrain loader.
 *
 * 16 kHz mono matches the ECAPA speaker model's own rate, so the backend's resample
 * step becomes a no-op and the upload stays small against the reference size cap.
 */

import {
  FaCheck as Check,
  FaSpinner as LoaderCircle,
  FaMicrophone as Mic,
  FaSyncAlt as RefreshCw,
  FaSquare as Square,
  FaTimes as X,
} from "react-icons/fa";
import { useCallback, useEffect, useRef, useState } from "react";

const TARGET_SAMPLE_RATE = 16000;
const MAX_SECONDS = 60;
const MIN_SECONDS = 2;

/** Encode mono float samples as a 16-bit PCM WAV (RIFF) blob. */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeAscii = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  };

  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk length
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate: rate * channels * 2 bytes
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeAscii(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let index = 0; index < samples.length; index += 1, offset += 2) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

/** Decode whatever MediaRecorder produced and downmix to mono at the model's rate. */
async function toMonoPcm(blob: Blob): Promise<{ samples: Float32Array; sampleRate: number }> {
  const bytes = await blob.arrayBuffer();
  const decodeContext = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await decodeContext.decodeAudioData(bytes);
  } finally {
    void decodeContext.close();
  }

  const frames = Math.ceil(decoded.duration * TARGET_SAMPLE_RATE);
  try {
    // Resampling to exactly 16 kHz mono. Some browsers refuse unusual rates in an
    // OfflineAudioContext, so fall back to the decoded rate — the backend resamples
    // anyway, this is only an optimisation.
    const offline = new OfflineAudioContext(1, frames, TARGET_SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return { samples: rendered.getChannelData(0), sampleRate: TARGET_SAMPLE_RATE };
  } catch {
    const channel = decoded.getChannelData(0);
    return { samples: new Float32Array(channel), sampleRate: Math.round(decoded.sampleRate) };
  }
}

function describeMicError(error: unknown): string {
  const name = (error as { name?: string } | null)?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Microphone access was blocked. Allow microphone permission for this site in your browser, then try again.";
  }
  if (name === "NotFoundError") {
    return "No microphone was found on this device. You can still choose an existing audio file instead.";
  }
  if (name === "NotReadableError") {
    return "The microphone is already in use by another application. Close it and try again.";
  }
  return "Recording could not be started. You can still choose an existing audio file instead.";
}

export function VoiceRecorder({ onRecorded, onClose }: { onRecorded: (file: File) => void; onClose: () => void }) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<number | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [encoding, setEncoding] = useState(false);
  const [error, setError] = useState("");
  const [take, setTake] = useState<{ file: File; url: string; seconds: number } | null>(null);

  const releaseDevice = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const clearTick = useCallback(() => {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    clearTick();
    releaseDevice();
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, [clearTick, releaseDevice]);

  const discardTake = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setTake(null);
    setSeconds(0);
  }, []);

  const stop = useCallback(() => {
    clearTick();
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    setRecording(false);
  }, [clearTick]);

  const start = useCallback(async () => {
    setError("");
    discardTake();

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser does not support in-page recording. Choose an existing audio file instead.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = () => {
        releaseDevice();
        const raw = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (raw.size === 0) {
          setError("Nothing was recorded. Try again.");
          return;
        }

        setEncoding(true);
        void toMonoPcm(raw)
          .then(({ samples, sampleRate }) => {
            const wav = encodeWav(samples, sampleRate);
            const stamp = new Date().toISOString().replace(/[:.]/g, "-");
            const file = new File([wav], `voice-recording-${stamp}.wav`, { type: "audio/wav" });
            previewUrlRef.current = URL.createObjectURL(wav);
            setTake({ file, url: previewUrlRef.current, seconds: Math.round(samples.length / sampleRate) });
          })
          .catch(() => setError("The recording could not be converted to WAV. Choose an existing audio file instead."))
          .finally(() => setEncoding(false));
      };

      recorder.start();
      setRecording(true);
      setSeconds(0);
      tickRef.current = window.setInterval(() => {
        setSeconds((previous) => {
          const next = previous + 1;
          // Hard cap so a forgotten recording cannot grow past the reference size limit.
          if (next >= MAX_SECONDS) stop();
          return next;
        });
      }, 1000);
    } catch (cause) {
      setError(describeMicError(cause));
      releaseDevice();
    }
  }, [discardTake, releaseDevice, stop]);

  const accept = useCallback(() => {
    if (!take) return;
    onRecorded(take.file);
    onClose();
  }, [onClose, onRecorded, take]);

  const tooShort = take !== null && take.seconds < MIN_SECONDS;

  return (
    <div className="capture-backdrop" role="dialog" aria-modal="true" aria-label="Record a reference voice sample">
      <div className="capture-modal">
        <div className="capture-modal-head">
          <div><Mic size={18} /><strong>Record a reference voice sample</strong></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close recorder"><X size={17} /></button>
        </div>

        <p className="capture-hint">
          Speak normally for {MIN_SECONDS}–{MAX_SECONDS} seconds in a quiet room — reading any two or three
          sentences works well. Longer, cleaner speech gives the speaker model more to compare.
          The recording stays on this device until you submit the form.
        </p>

        {error && <div className="capture-error" role="alert">{error}</div>}

        <div className="recorder-stage">
          <div className={`recorder-orb ${recording ? "live" : ""}`}>
            {encoding ? <LoaderCircle className="spin" size={26} /> : <Mic size={26} />}
          </div>
          <div className="recorder-readout">
            <strong>
              {encoding
                ? "Converting to WAV…"
                : recording
                  ? `Recording · ${seconds}s`
                  : take
                    ? `Recorded · ${take.seconds}s`
                    : "Ready to record"}
            </strong>
            <small>
              {recording
                ? `Recording stops automatically at ${MAX_SECONDS}s.`
                : take
                  ? "Play it back below, then keep it or record again."
                  : "16 kHz mono WAV — the format the speaker model reads."}
            </small>
          </div>
        </div>

        {take && <audio className="audio-player" src={take.url} controls />}
        {tooShort && (
          <div className="capture-error" role="alert">
            That clip is under {MIN_SECONDS} seconds, which is usually too short for a reliable voice
            comparison. Record a longer sample.
          </div>
        )}

        <div className="capture-actions">
          {!recording && !take && (
            <button type="button" className="btn btn-primary" onClick={() => void start()} disabled={encoding}>
              <Mic size={17} /> Start recording
            </button>
          )}
          {recording && (
            <button type="button" className="btn btn-danger" onClick={stop}><Square size={15} /> Stop recording</button>
          )}
          {take && (
            <>
              <button type="button" className="btn btn-secondary" onClick={() => void start()}><RefreshCw size={16} /> Record again</button>
              <button type="button" className="btn btn-success" onClick={accept} disabled={tooShort}><Check size={17} /> Use this recording</button>
            </>
          )}
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

"use client";

/**
 * Take a reference photo with the device camera.
 *
 * The captured still is encoded as JPEG because the enrollment endpoint gates on
 * file extension (IMAGE_EXTENSIONS in backend/main.py), so the produced File is
 * named `.jpg` with a matching MIME type. Nothing is uploaded from here — the
 * component hands a File back to the form and the normal enrollment request
 * carries it, so the server still hashes the bytes it actually receives.
 */

import { Camera, Check, LoaderCircle, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

const IDEAL_WIDTH = 1280;
const IDEAL_HEIGHT = 720;
const JPEG_QUALITY = 0.92;

/** Turn a getUserMedia rejection into something a non-technical user can act on. */
function describeCameraError(error: unknown): string {
  const name = (error as { name?: string } | null)?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Camera access was blocked. Allow camera permission for this site in your browser, then try again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No camera was found on this device. You can still choose an existing photo file instead.";
  }
  if (name === "NotReadableError") {
    return "The camera is already in use by another application. Close it and try again.";
  }
  return "The camera could not be started. You can still choose an existing photo file instead.";
}

export function CameraCapture({ onCapture, onClose }: { onCapture: (file: File) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const [starting, setStarting] = useState(true);
  const [error, setError] = useState("");
  const [shot, setShot] = useState<{ file: File; url: string } | null>(null);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const discardShot = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setShot(null);
  }, []);

  // Start the camera on mount and release the device on unmount. Without the
  // explicit track stop the camera indicator light stays on after closing.
  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser does not support camera capture. Choose an existing photo file instead.");
        setStarting(false);
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: IDEAL_WIDTH }, height: { ideal: IDEAL_HEIGHT } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch (cause) {
        if (!cancelled) setError(describeCameraError(cause));
      } finally {
        if (!cancelled) setStarting(false);
      }
    }

    void start();
    return () => {
      cancelled = true;
      stopStream();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, [stopStream]);

  const takeShot = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      setError("This browser could not encode the captured frame.");
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setError("The photo could not be encoded. Try again or choose a file instead.");
          return;
        }
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        const file = new File([blob], `camera-capture-${stamp}.jpg`, { type: "image/jpeg" });
        previewUrlRef.current = URL.createObjectURL(blob);
        setShot({ file, url: previewUrlRef.current });
      },
      "image/jpeg",
      JPEG_QUALITY,
    );
  }, []);

  const accept = useCallback(() => {
    if (!shot) return;
    // Hand the File to the form before tearing down, then release the camera.
    onCapture(shot.file);
    stopStream();
    onClose();
  }, [onCapture, onClose, shot, stopStream]);

  return (
    <div className="capture-backdrop" role="dialog" aria-modal="true" aria-label="Take a reference photo">
      <div className="capture-modal">
        <div className="capture-modal-head">
          <div><Camera size={18} /><strong>Take a reference photo</strong></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close camera"><X size={17} /></button>
        </div>

        <p className="capture-hint">
          Look straight at the camera in even lighting. A clear frontal face gives the most reliable
          identity comparison. The photo stays on this device until you submit the form.
        </p>

        {error ? (
          <div className="capture-error" role="alert">{error}</div>
        ) : (
          <div className="capture-stage">
            {/* The live feed stays mounted behind the still so the stream is not torn
                down on retake. */}
            <video
              ref={videoRef}
              className="capture-video"
              style={{ display: shot ? "none" : "block" }}
              autoPlay
              playsInline
              muted
            />
            {/* eslint-disable-next-line @next/next/no-img-element -- the source is a
                local blob: URL that next/image cannot optimise or proxy. */}
            {shot && <img className="capture-video" src={shot.url} alt="Captured reference photo preview" />}
            {starting && <div className="capture-loading"><LoaderCircle className="spin" size={22} /><span>Starting camera…</span></div>}
          </div>
        )}

        <div className="capture-actions">
          {!error && !shot && (
            <button type="button" className="btn btn-primary" onClick={takeShot} disabled={starting}>
              <Camera size={17} /> Capture photo
            </button>
          )}
          {shot && (
            <>
              <button type="button" className="btn btn-secondary" onClick={discardShot}><RefreshCw size={16} /> Retake</button>
              <button type="button" className="btn btn-success" onClick={accept}><Check size={17} /> Use this photo</button>
            </>
          )}
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

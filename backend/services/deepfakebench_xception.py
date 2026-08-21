"""DeepfakeBench-compatible Xception inference network.

Derived from SCLBD/DeepfakeBench's training/networks/xception.py.
DeepfakeBench is licensed CC BY-NC 4.0; use this adapter and its checkpoint only
for non-commercial research, evaluation, or this hackathon prototype.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class SeparableConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=1, stride=1,
                 padding=0, dilation=1, bias=False):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, in_channels, kernel_size, stride,
                               padding, dilation, groups=in_channels, bias=bias)
        self.pointwise = nn.Conv2d(in_channels, out_channels, 1, 1, 0, 1, 1,
                                   bias=bias)

    def forward(self, x):
        return self.pointwise(self.conv1(x))


class Block(nn.Module):
    def __init__(self, in_filters, out_filters, reps, strides=1,
                 start_with_relu=True, grow_first=True):
        super().__init__()
        if out_filters != in_filters or strides != 1:
            self.skip = nn.Conv2d(in_filters, out_filters, 1, stride=strides,
                                  bias=False)
            self.skipbn = nn.BatchNorm2d(out_filters)
        else:
            self.skip = None

        relu = nn.ReLU(inplace=True)
        layers = []
        filters = in_filters
        if grow_first:
            layers.extend([relu, SeparableConv2d(in_filters, out_filters, 3, 1, 1),
                           nn.BatchNorm2d(out_filters)])
            filters = out_filters
        for _ in range(reps - 1):
            layers.extend([relu, SeparableConv2d(filters, filters, 3, 1, 1),
                           nn.BatchNorm2d(filters)])
        if not grow_first:
            layers.extend([relu, SeparableConv2d(in_filters, out_filters, 3, 1, 1),
                           nn.BatchNorm2d(out_filters)])
        if not start_with_relu:
            layers = layers[1:]
        else:
            layers[0] = nn.ReLU(inplace=False)
        if strides != 1:
            layers.append(nn.MaxPool2d(3, strides, 1))
        self.rep = nn.Sequential(*layers)

    def forward(self, inp):
        x = self.rep(inp)
        skip = self.skipbn(self.skip(inp)) if self.skip is not None else inp
        return x + skip


class Xception(nn.Module):
    """The two-class Xception configuration used by DeepfakeBench's checkpoint."""
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 32, 3, 2, 0, bias=False)
        self.bn1 = nn.BatchNorm2d(32)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(32, 64, 3, bias=False)
        self.bn2 = nn.BatchNorm2d(64)
        self.block1 = Block(64, 128, 2, 2, start_with_relu=False, grow_first=True)
        self.block2 = Block(128, 256, 2, 2, start_with_relu=True, grow_first=True)
        self.block3 = Block(256, 728, 2, 2, start_with_relu=True, grow_first=True)
        self.block4 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block5 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block6 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block7 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block8 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block9 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block10 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block11 = Block(728, 728, 3, 1, start_with_relu=True, grow_first=True)
        self.block12 = Block(728, 1024, 2, 2, start_with_relu=True, grow_first=False)
        self.conv3 = SeparableConv2d(1024, 1536, 3, 1, 1)
        self.bn3 = nn.BatchNorm2d(1536)
        self.conv4 = SeparableConv2d(1536, 2048, 3, 1, 1)
        self.bn4 = nn.BatchNorm2d(2048)
        self.last_linear = nn.Linear(2048, 2)
        # Present in the released state dict, but unused by the original mode.
        self.adjust_channel = nn.Sequential(nn.Conv2d(2048, 512, 1, 1),
                                            nn.BatchNorm2d(512),
                                            nn.ReLU(inplace=False))

    def features(self, x):
        x = self.relu(self.bn1(self.conv1(x)))
        x = self.relu(self.bn2(self.conv2(x)))
        for block in (self.block1, self.block2, self.block3, self.block4,
                      self.block5, self.block6, self.block7, self.block8,
                      self.block9, self.block10, self.block11, self.block12):
            x = block(x)
        x = self.relu(self.bn3(self.conv3(x)))
        return self.bn4(self.conv4(x))

    def forward(self, x):
        x = self.relu(self.features(x))
        x = F.adaptive_avg_pool2d(x, (1, 1)).flatten(1)
        return self.last_linear(x)

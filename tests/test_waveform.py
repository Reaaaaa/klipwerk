"""Tests for the vectorized waveform downsampler.

The actual ffmpeg invocation isn't tested here — that would require a
real video file and is covered by integration tests. We just verify
the numpy-side reshape/peak logic that replaced the Python loop.
"""
from __future__ import annotations

import numpy as np
import pytest

from klipwerk.workers.waveform import WaveformWorker


def test_downsample_shape_matches_width():
    samples = np.random.RandomState(0).uniform(-1, 1, 10_000).astype(np.float32)
    peaks = WaveformWorker._downsample(samples, 500)
    assert peaks.shape == (500,)


def test_downsample_normalized_to_0_1():
    samples = np.random.RandomState(0).uniform(-1, 1, 10_000).astype(np.float32)
    peaks = WaveformWorker._downsample(samples, 500)
    assert peaks.min() >= 0
    assert peaks.max() <= 1.0 + 1e-6


def test_downsample_all_zero_input():
    samples = np.zeros(5000, dtype=np.float32)
    peaks = WaveformWorker._downsample(samples, 200)
    assert peaks.shape == (200,)
    assert np.allclose(peaks, 0.0)


def test_downsample_fewer_samples_than_width():
    """When the clip is shorter than the target width, peaks are padded."""
    samples = np.array([0.1, 0.5, 0.9, 0.3], dtype=np.float32)
    peaks = WaveformWorker._downsample(samples, 100)
    assert peaks.shape == (100,)
    # Peaks are normalized — at least one entry should be 1.0 (the max)
    assert np.isclose(peaks.max(), 1.0)


def test_downsample_peak_detection():
    """Given a known spike in one chunk, it should dominate that bucket."""
    samples = np.zeros(1000, dtype=np.float32)
    samples[500] = 0.7   # single spike in the middle
    peaks = WaveformWorker._downsample(samples, 10)
    # Middle bucket (index ~5) should be the maximum
    assert peaks.argmax() == 5
    assert np.isclose(peaks.max(), 1.0)  # normalized to 1


@pytest.mark.parametrize("width", [1, 10, 100, 1000, 5000])
def test_downsample_various_widths(width):
    samples = np.random.RandomState(42).uniform(-1, 1, 10_000).astype(np.float32)
    peaks = WaveformWorker._downsample(samples, width)
    assert peaks.shape == (width,)

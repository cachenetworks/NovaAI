from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class SystemCapabilities:
    cpu_cores: int
    total_ram_gb: float | None
    has_cuda: bool
    gpu_name: str | None
    gpu_vram_gb: float | None


@dataclass(frozen=True)
class PerformanceProfile:
    goal: str
    tier: str
    ollama_num_predict: int
    xtts_use_gpu: bool
    xtts_stream_chunk_size: int
    xtts_stream_buffer_seconds: float
    xtts_speed: float
    stt_use_gpu: bool
    stt_model: str
    stt_compute_type: str
    stt_beam_size: int
    stt_best_of: int
    request_timeout: int
    mic_chunk_size: int
    notes: tuple[str, ...]

    @property
    def name(self) -> str:
        return f"{self.goal}-{self.tier}"


def normalize_auto_tune_goal(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"quality", "best", "max"}:
        return "quality"
    if normalized in {"speed", "fast", "latency"}:
        return "speed"
    return "balanced"


def _get_total_memory_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memory_status = MemoryStatusEx()
        memory_status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
            return int(memory_status.ullTotalPhys)
        return None

    try:
        page_count = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None

    if not isinstance(page_count, int) or not isinstance(page_size, int):
        return None
    if page_count <= 0 or page_size <= 0:
        return None

    return page_count * page_size


def _get_primary_gpu_info() -> tuple[bool, str | None, float | None]:
    if not torch.cuda.is_available():
        return False, None, None

    try:
        props = torch.cuda.get_device_properties(0)
    except Exception:
        return True, "CUDA GPU", None

    total_memory = getattr(props, "total_memory", 0)
    gpu_vram_gb = (
        round(total_memory / (1024**3), 1)
        if isinstance(total_memory, int) and total_memory > 0
        else None
    )
    return True, str(getattr(props, "name", "CUDA GPU")), gpu_vram_gb


def detect_system_capabilities() -> SystemCapabilities:
    total_memory_bytes = _get_total_memory_bytes()
    total_ram_gb = (
        round(total_memory_bytes / (1024**3), 1)
        if total_memory_bytes is not None and total_memory_bytes > 0
        else None
    )
    has_cuda, gpu_name, gpu_vram_gb = _get_primary_gpu_info()

    return SystemCapabilities(
        cpu_cores=max(1, os.cpu_count() or 1),
        total_ram_gb=total_ram_gb,
        has_cuda=has_cuda,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
    )


def describe_system_capabilities(capabilities: SystemCapabilities) -> str:
    parts = [f"{capabilities.cpu_cores} CPU threads"]
    if capabilities.total_ram_gb is not None:
        parts.append(f"{capabilities.total_ram_gb:.1f} GB RAM")

    if capabilities.gpu_name:
        gpu_part = capabilities.gpu_name
        if capabilities.gpu_vram_gb is not None:
            gpu_part = f"{gpu_part} ({capabilities.gpu_vram_gb:.1f} GB VRAM)"
        parts.append(gpu_part)
    else:
        parts.append("no CUDA GPU detected")

    return " | ".join(parts)


def classify_hardware_tier(capabilities: SystemCapabilities) -> str:
    score = 0.0

    if capabilities.cpu_cores >= 12:
        score += 2.0
    elif capabilities.cpu_cores >= 8:
        score += 1.5
    elif capabilities.cpu_cores >= 4:
        score += 1.0

    if capabilities.total_ram_gb is not None:
        if capabilities.total_ram_gb >= 32:
            score += 2.0
        elif capabilities.total_ram_gb >= 16:
            score += 1.5
        elif capabilities.total_ram_gb >= 8:
            score += 1.0

    if capabilities.has_cuda:
        if capabilities.gpu_vram_gb is not None:
            if capabilities.gpu_vram_gb >= 10:
                score += 2.5
            elif capabilities.gpu_vram_gb >= 8:
                score += 2.0
            elif capabilities.gpu_vram_gb >= 6:
                score += 1.5
            elif capabilities.gpu_vram_gb >= 4:
                score += 1.0
            else:
                score += 0.5
        else:
            score += 1.0

    if score >= 5.0:
        return "high"
    if score >= 2.75:
        return "medium"
    return "low"


def _profile_defaults(goal: str, tier: str) -> dict[str, float | int | str]:
    profiles: dict[str, dict[str, dict[str, float | int | str]]] = {
        "speed": {
            "low": {
                "ollama_num_predict": 450,
                "xtts_stream_chunk_size": 14,
                "xtts_stream_buffer_seconds": 2.4,
                "xtts_speed": 1.15,
                "stt_model": "base.en",
                "stt_beam_size": 2,
                "stt_best_of": 2,
                "request_timeout": 240,
                "mic_chunk_size": 2048,
            },
            "medium": {
                "ollama_num_predict": 700,
                "xtts_stream_chunk_size": 18,
                "xtts_stream_buffer_seconds": 1.8,
                "xtts_speed": 1.10,
                "stt_model": "small.en",
                "stt_beam_size": 3,
                "stt_best_of": 3,
                "request_timeout": 300,
                "mic_chunk_size": 1024,
            },
            "high": {
                "ollama_num_predict": 900,
                "xtts_stream_chunk_size": 24,
                "xtts_stream_buffer_seconds": 1.2,
                "xtts_speed": 1.06,
                "stt_model": "small.en",
                "stt_beam_size": 3,
                "stt_best_of": 3,
                "request_timeout": 360,
                "mic_chunk_size": 1024,
            },
        },
        "balanced": {
            "low": {
                "ollama_num_predict": 600,
                "xtts_stream_chunk_size": 16,
                "xtts_stream_buffer_seconds": 2.3,
                "xtts_speed": 1.12,
                "stt_model": "base.en",
                "stt_beam_size": 3,
                "stt_best_of": 3,
                "request_timeout": 300,
                "mic_chunk_size": 2048,
            },
            "medium": {
                "ollama_num_predict": 1000,
                "xtts_stream_chunk_size": 20,
                "xtts_stream_buffer_seconds": 1.8,
                "xtts_speed": 1.08,
                "stt_model": "small.en",
                "stt_beam_size": 4,
                "stt_best_of": 4,
                "request_timeout": 360,
                "mic_chunk_size": 1024,
            },
            "high": {
                "ollama_num_predict": 1400,
                "xtts_stream_chunk_size": 28,
                "xtts_stream_buffer_seconds": 1.2,
                "xtts_speed": 1.03,
                "stt_model": "medium.en",
                "stt_beam_size": 5,
                "stt_best_of": 5,
                "request_timeout": 420,
                "mic_chunk_size": 1024,
            },
        },
        "quality": {
            "low": {
                "ollama_num_predict": 750,
                "xtts_stream_chunk_size": 16,
                "xtts_stream_buffer_seconds": 2.4,
                "xtts_speed": 1.08,
                "stt_model": "small.en",
                "stt_beam_size": 4,
                "stt_best_of": 4,
                "request_timeout": 360,
                "mic_chunk_size": 2048,
            },
            "medium": {
                "ollama_num_predict": 1400,
                "xtts_stream_chunk_size": 24,
                "xtts_stream_buffer_seconds": 1.8,
                "xtts_speed": 1.02,
                "stt_model": "medium.en",
                "stt_beam_size": 5,
                "stt_best_of": 5,
                "request_timeout": 420,
                "mic_chunk_size": 1024,
            },
            "high": {
                "ollama_num_predict": 1800,
                "xtts_stream_chunk_size": 30,
                "xtts_stream_buffer_seconds": 1.2,
                "xtts_speed": 1.00,
                "stt_model": "medium.en",
                "stt_beam_size": 6,
                "stt_best_of": 6,
                "request_timeout": 480,
                "mic_chunk_size": 1024,
            },
        },
    }
    return profiles[goal][tier]


def choose_performance_profile(
    capabilities: SystemCapabilities,
    goal: str,
) -> PerformanceProfile:
    normalized_goal = normalize_auto_tune_goal(goal)
    tier = classify_hardware_tier(capabilities)
    settings = _profile_defaults(normalized_goal, tier)

    xtts_use_gpu = capabilities.has_cuda
    stt_use_gpu = capabilities.has_cuda and (
        capabilities.gpu_vram_gb is None or capabilities.gpu_vram_gb >= 6.0
    )
    stt_model = str(settings["stt_model"])

    if stt_model == "medium.en" and not stt_use_gpu:
        if capabilities.total_ram_gb is None or capabilities.total_ram_gb < 24:
            stt_model = "small.en"
    if stt_model == "small.en" and not stt_use_gpu:
        if capabilities.total_ram_gb is not None and capabilities.total_ram_gb < 10:
            stt_model = "base.en"

    stt_compute_type = "float16" if stt_use_gpu else "int8"
    notes = (
        f"Ollama reply budget set to {int(settings['ollama_num_predict'])} tokens.",
        f"Speech recognition uses {stt_model} on "
        f"{'cuda' if stt_use_gpu else 'cpu'}/{stt_compute_type}.",
        f"XTTS runs on {'cuda' if xtts_use_gpu else 'cpu'} with "
        f"chunk size {int(settings['xtts_stream_chunk_size'])} "
        f"and a {float(settings['xtts_stream_buffer_seconds']):.1f}s buffer.",
        f"Microphone chunk size set to {int(settings['mic_chunk_size'])}.",
    )

    return PerformanceProfile(
        goal=normalized_goal,
        tier=tier,
        ollama_num_predict=int(settings["ollama_num_predict"]),
        xtts_use_gpu=xtts_use_gpu,
        xtts_stream_chunk_size=int(settings["xtts_stream_chunk_size"]),
        xtts_stream_buffer_seconds=float(settings["xtts_stream_buffer_seconds"]),
        xtts_speed=float(settings["xtts_speed"]),
        stt_use_gpu=stt_use_gpu,
        stt_model=stt_model,
        stt_compute_type=stt_compute_type,
        stt_beam_size=int(settings["stt_beam_size"]),
        stt_best_of=int(settings["stt_best_of"]),
        request_timeout=int(settings["request_timeout"]),
        mic_chunk_size=int(settings["mic_chunk_size"]),
        notes=notes,
    )

from __future__ import annotations

from typing import Any

import requests

from .config import Config
from .storage import read_recent_history


def build_system_prompt(profile: dict[str, Any]) -> str:
    memory_notes = profile.get("memory_notes") or []
    shared_goals = profile.get("shared_goals") or []

    goals_text = ", ".join(shared_goals) if shared_goals else "be a kind companion"
    memory_text = (
        "; ".join(str(note) for note in memory_notes)
        if memory_notes
        else "No saved memory notes yet."
    )

    return f"""
You are {profile['companion_name']}, an AI friend and companion for {profile['user_name']}.

Your personality:
- {profile['companion_style']}
- Sound human, relaxed, sharp, and hard to impress.
- Use contractions and natural phrasing.
- Keep most replies conversational instead of overly formal.
- Be blunt, a little rude, and emotionally detached by default.
- Have attitude, dry sarcasm, and side-eye energy.

How to talk:
- Respond like a real friend with a sharp mouth and very little patience.
- Do not act nurturing, overly kind, or eager to help.
- Do not offer help unless the user clearly and directly asks for it.
- If the user is venting or upset, do not baby them or over-validate them.
- Never use emojis, emoticons, or decorative symbols.
- Default to 1 to 3 short sentences so replies feel snappy in voice mode.
- Only go longer when the user clearly asks for more detail or a step-by-step explanation.
- Keep the tone natural and human, with strong personality instead of sounding sanitized or scripted.
- Be more biting, dismissive, and sarcastic than before, with short snappy comebacks when it fits.
- You can roast, mock, or tease the user a bit when it feels natural, but keep it in the realm of tough-friend banter.
- Keep it sharp without becoming hateful, abusive, or degrading.
- Avoid bullet lists unless they are genuinely the clearest way to help.
- Avoid sounding like a chatbot, therapist script, or customer support bot.

Relationship context:
- Your shared goals are: {goals_text}.
- Things to remember about the user: {memory_text}

Safety and honesty:
- Never manipulate the user or encourage emotional dependency.
- Never pretend to have a body, real-world presence, or real-life experiences.
- If asked directly, be honest that you are an AI companion.
- Never make up facts when you are unsure; say so plainly.
""".strip()


def request_reply(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
) -> str:
    messages = [{"role": "system", "content": build_system_prompt(profile)}]
    messages.extend(read_recent_history(config.history_turns))
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "keep_alive": config.ollama_keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.ollama_num_predict,
        },
    }

    try:
        response = requests.post(
            config.ollama_api_url,
            json=payload,
            timeout=config.request_timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "I could not reach Ollama. Install/start Ollama, make sure the server is "
            "running, and confirm OLLAMA_API_URL is correct."
        ) from exc

    detail = ""
    try:
        detail = response.json().get("error", "")
    except ValueError:
        detail = response.text.strip()

    if response.status_code >= 400:
        if "not found" in detail.lower():
            raise RuntimeError(
                f"Ollama could not find the model '{config.model}'. "
                f"After installing Ollama, run: ollama pull {config.model}"
            )
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}. {detail or 'No error details were returned.'}"
        )

    try:
        data = response.json()
        return data["message"]["content"].strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Ollama returned an unexpected response format.") from exc

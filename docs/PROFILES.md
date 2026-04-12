# 🎭 Profiles Guide

NovaAI supports multiple companion profiles, each with its own personality, memory, and behaviour rules. Switch between a sarcastic best friend, a patient tutor, or a no-nonsense project manager in seconds.

---

## 🔄 Managing Profiles

### GUI

Navigate to the **Profiles** page:
- **Create** — enter a name and click Create
- **Clone** — duplicate an existing profile as a starting point
- **Activate** — switch the active companion
- **Delete** — remove a profile (you always need at least one)

### Terminal

```
/profiles              # list all profiles
/profile               # show current profile details
/profile use <id>      # switch to a different profile
/name <new name>       # rename the companion
/me <your name>        # set your display name
/remember <fact>       # add a memory note
```

---

## 📦 Profile Structure

Every profile contains these sections:

### Top-Level Fields

| Field | Description | Example |
|-------|-------------|---------|
| `profile_name` | Display name for this profile | `"Snarky Bot"` |
| `companion_name` | What the AI calls itself | `"NovaAI"` |
| `user_name` | What the AI calls you | `"Friend"` |
| `description` | Short description of the personality | `"Brutally honest companion"` |
| `companion_style` | Free-text personality description | `"blunt, dry, sharp-tongued..."` |
| `shared_goals` | List of conversation goals | `["keep replies short", ...]` |
| `memory_notes` | User-added memories | `["likes coffee", "hates Mondays"]` |
| `tags` | Searchable tags | `["default", "voice", "sassy"]` |

### 🏷️ Identity (`profile_details.identity`)

| Field | Description |
|-------|-------------|
| `companion_role` | What the AI is (e.g. "AI friend and companion") |
| `relationship_style` | How it relates to you (e.g. "casual, direct, and witty") |
| `companion_pronouns` | AI's pronouns (e.g. "they/them") |
| `user_pronouns` | Your pronouns |
| `timezone_hint` | Optional timezone |
| `locale` | Language locale (e.g. "en-US") |

### 💬 Conversation (`profile_details.conversation`)

| Field | Description |
|-------|-------------|
| `default_reply_length` | `"short"`, `"medium"`, or `"long"` |
| `allow_emojis` | Whether to use emojis |
| `response_pacing` | `"snappy"`, `"measured"`, or `"deliberate"` |
| `question_style` | How often to ask follow-ups |
| `explanation_style` | When to expand on answers |
| `proactivity` | Whether to volunteer information |
| `formatting_preference` | Paragraphs vs bullet lists |
| `verbosity_hint` | Natural language hint for reply length |

### 🎚️ Personality Sliders (`profile_details.personality_sliders`)

Scale of 0–100 for each trait:

| Slider | Low End | High End |
|--------|---------|----------|
| `warmth` | Cold, distant | Warm, caring |
| `sass` | Mild, polite | Maximum attitude |
| `directness` | Diplomatic | Blunt |
| `patience` | Snappy, impatient | Endlessly patient |
| `playfulness` | Serious | Goofy, jokey |
| `formality` | Casual | Professional |

### 🚧 Boundaries (`profile_details.boundaries`)

| Field | Description |
|-------|-------------|
| `allow_roasting` | Whether the AI can roast you |
| `roast_intensity` | `"light"`, `"medium"`, or `"heavy"` |
| `avoid_topics` | Topics the AI won't discuss |
| `disallowed_behaviors` | Things the AI must never do |
| `safety_overrides` | Hard safety rules |

### 🧠 Memory (`profile_details.memory`)

| Field | Description |
|-------|-------------|
| `long_term_preferences` | General preferences |
| `likes` | Things you like |
| `dislikes` | Things you dislike |
| `personal_facts` | Facts about you |
| `inside_jokes` | Shared jokes |
| `projects` | Current projects |

### 🔊 Voice (`profile_details.voice`)

| Field | Description |
|-------|-------------|
| `speech_style` | How the AI should sound |
| `delivery_notes` | Pacing and tone hints |
| `pronunciation_notes` | Special pronunciation rules |
| `voice_persona_keywords` | Keywords describing the voice |

### 📜 Custom Rules (`profile_details.custom_rules`)

| Field | Description |
|-------|-------------|
| `must_follow` | Hard rules the AI always follows |
| `nice_to_have` | Soft preferences |
| `system_notes` | Extra system prompt text |

---

## 🎨 Example: Creating a Patient Tutor

```json
{
  "profile_name": "Study Buddy",
  "companion_name": "Sage",
  "companion_style": "patient, encouraging, explains things step by step",
  "shared_goals": [
    "help the user learn and understand",
    "break complex topics into simple parts",
    "celebrate progress"
  ],
  "profile_details": {
    "personality_sliders": {
      "warmth": 85,
      "sass": 10,
      "directness": 60,
      "patience": 95,
      "playfulness": 40,
      "formality": 30
    },
    "conversation": {
      "default_reply_length": "medium",
      "response_pacing": "measured",
      "explanation_style": "expand by default"
    }
  }
}
```

---

## 💡 Tips

- **Start with a clone** — duplicate the default profile and tweak it instead of starting from scratch.
- **Personality sliders matter** — the system prompt builds dynamically from these values. Small changes make noticeable differences.
- **Memory notes persist** — anything you `/remember` is stored and included in every conversation.
- **Feature data follows the profile** — each profile has its own reminders, todos, shopping list, calendar, and alarms.

# Private skin

The pet's appearance and persona can be replaced at home without touching the repository.
Everything lives in the data directory (`PET_DATA_DIR`, by default `~/pet-data-dev/`), which is never committed.
Each skin is a folder `skin-<id>/` (lowercase letters, digits, `-` or `_`), for example `skin-goku/` and `skin-pika/`.
The built-in blue British Shorthair stays in the repo as the default and is always offered as the skin `cat`.

When there is more than one skin, the page shows a round button in the top left with the current buddy. Tapping it opens a
picker; choosing another buddy ends a running exploration, switches the name, catchphrase, tone, voice and cue at once, and
reloads the page. The choice is saved as `"skin"` in `settings.json`, so it survives restarts. An older single `skin/` folder
is still used when `"skin"` is not set.

Artwork you put there is your own business (for example something you generated for private, non-commercial use).
Do not commit it: the repository is public.

## Files

```
~/pet-data-dev/skin-goku/
  skin.json
  idle.png          required
  listening.png     optional, falls back to idle
  thinking.png      optional
  speaking.png      optional
  cue.m4a           optional, see "cue" below
```

Images: front-facing, centered, transparent PNG (WebP or JPG also work), about 1024 x 1024, the same character in every state.

## skin.json

```json
{
  "name":  {"zh": "皮皮", "en": "Pippi"},
  "sound": {"zh": "皮卡", "en": "pika"},
  "style": {"zh": "可爱、活泼", "en": "cute and playful"},
  "voice": {"zh": "zf_074", "en": "af_sol"},
  "speed": 1.05,
  "images": {
    "idle": "idle.png",
    "listening": "listening.png",
    "thinking": "thinking.png",
    "speaking": "speaking.png"
  }
}
```

- `name`: how the pet refers to itself ("I am Pippi"). With a name set, the default look ("a program kitten that looks like a
  British Shorthair") is dropped; add `"look": {"zh": ..., "en": ...}` only if you want a description after the name.
- `sound`: the catchphrase, used at most once per answer, in the lookup filler ("Pika, let me look that up!") and the farewell.
- `not_real`: optional; defaults to "a real <name>". It is what the pet says it is not, when asked whether it is real.
- `style`: optional speaking tone, added to every prompt as "说话<style>。" / "Talk <style>." Keep it short: the whole
  Chinese prompt must stay under 200 characters (every turn re-reads it). The built-in kitten's tone is "温柔、好奇".
- `voice`: optional Kokoro voice names per language. Only converted voices work; convert all official voices once with
  `uv run python scripts/convert_kokoro.py --voices all --voices-only` (about 50 MB). Chinese has `zf_*` (female) and `zm_*`
  (male) voices; English has only `af_maple`, `af_sol` and `bf_vale`. An unknown name falls back to the default voice.
- `speed`: optional speech speed, 0.7 to 1.4 (default 1.0).
- `cue`: optional audio file in the folder (wav, mp3, m4a, at most 3 seconds are used), played the moment the pet has heard
  the child, and also spoken in place of the catchphrase inside answers ("皮卡,我去查一查!" plays the clip, then the voice).
  Use a recording you have the right to use for yourself; the project does not ship or download character audio.
  Without it the pet's own voice says the catchphrase ("嘿!", "皮卡!"); the built-in kitten meows.
- `sound_pitch`: optional, 1.0 to 2.0. Without a `cue` file, the catchphrase is spoken by the skin's voice pitched up by
  this factor (1.5 makes a squeaky "pika"), both as the cue and inside answers.
- `card`: optional character facts per language (where the character is from, abilities, friends, likes, how it talks,
  and common mix-ups to avoid, e.g. Goku from Dragon Ball does not do the 72 transformations of Journey to the West).
  It is added to the prompt only when the child asks about the character or mentions one of `card_keywords` (or its
  name), so other turns stay fast. Keep it under about 160 Chinese characters.
- `card_keywords`: optional list of words that bring the card in ("七龙珠", "龟派气功", "Pokémon").
- `phrases`: optional fixed lines in the character's own words, each per language: `filler` (before a lookup),
  `farewell`, `ready` (when the child is about to pose a riddle), `not_heard` (a lone word the pet did not catch).
- Missing keys keep the defaults; text keys are per language (`zh`, `en`).

## Name and home-screen icon

The browser tab, the "Add to Home Screen" name and the web app manifest use the skin's English name (`name.en`), default
"Curiosity Buddy". The home-screen icon is built from the skin's `idle.png` on the page background; without a skin it is the
built-in cat icon. After changing a skin, remove the old icon from the iPad home screen and add the page again so iOS picks up
the new name and icon.

## What stays the same

- Hard constraint 4 still applies: the pet does not pretend to be alive. In normal conversation it just uses its name;
  only when asked whether it is real does it say it is a program, not a real <name>.
- The round badge in the corner of the picture replaces the collar light: it is the "this is a program" marker and changes
  color with the state (idle yellow, listening green, thinking purple, speaking orange). It cannot be turned off.
- The page keeps its motion: breathing when idle, a float when thinking, a bounce when speaking.

## From a 2x2 character sheet

If an image tool gave you one picture with four poses in a 2x2 grid (idle, listening / thinking, speaking), the script cuts,
removes the background, aligns and writes the folder in one go:

```bash
uv run --with pillow python scripts/make_skin.py sheet.png ~/pet-data-dev/skin-name --name-zh 名字 --name-en Name --sound-zh 喵 --sound-en meow
```

## Applying changes

A new `skin-<id>/` folder appears in the picker on the next page load. After editing a `skin.json`, choose that skin again in
the picker (or restart `pet-server`) so the voice and prompt are reloaded; image files can be swapped any time.
`GET /skin.json` shows the active skin, `GET /skins.json` what the picker offers.

import os, json, time, requests, tempfile, subprocess
from pathlib import Path
from datetime import datetime

from moviepy import ImageClip, TextClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from supabase import create_client

# ── ENV ───────────────────────────────────────
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_SERVICE_KEY"]
CLAUDE_KEY    = os.environ["ANTHROPIC_API_KEY"]
EL_KEY        = os.environ["ELEVENLABS_API_KEY"]
EL_VOICE      = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
YT_REFRESH    = os.environ["YOUTUBE_REFRESH_TOKEN"]
YT_CLIENT_ID  = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SEC = os.environ["YOUTUBE_CLIENT_SECRET"]

CDN  = "https://img.veluera.beauty/product-images"
SITE = "https://veluera.beauty/products"
W, H = 1920, 1080

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── TOPICS ────────────────────────────────────
TOPICS = [
    {"topic": "Top 10 Luxus-Parfums unter 30 Euro",
     "category": "Parfum", "max_price": 50,
     "lang": "de", "audience": "Parfum-Liebhaber, 25-45, DACH"},
    {"topic": "Best Skincare Routine under 25 Euro",
     "category": "Hautpflege", "max_price": 40,
     "lang": "en", "audience": "Skincare enthusiasts, 20-35, EU"},
    {"topic": "Top 10 Haarpflege Geheimtipps 2026",
     "category": "Haarpflege", "max_price": 35,
     "lang": "de", "audience": "Frauen, 25-50, DACH"},
    {"topic": "Budget Parfums die wie Designer riechen",
     "category": "Parfum", "max_price": 30,
     "lang": "de", "audience": "Duft-Einsteiger, 18-35, EU"},
]

# ── 1: PRODUKTAUSWAHL ─────────────────────────
def select_products(category, max_price, limit=10):
    import random
    r = sb.table("master_products").select(
        "id,name,brand,category,description,sale_price,ean"
    ).eq("category", category).lte(
        "sale_price", max_price
    ).gte("sale_price", 10).not_.is_("ean", "null").limit(limit * 4).execute()
    items = r.data or []
    random.shuffle(items)
    out = []
    for p in items:
        if p.get("ean"):
            p["title"]         = p.get("name", "")
            p["image_url"]     = f"{CDN}/{p['ean']}.jpg"
            p["affiliate_url"] = f"{SITE}/{p['id']}"
            out.append(p)
        if len(out) >= limit:
            break
    return out

# ── 2: CLAUDE SKRIPT ──────────────────────────
PROMPT = (
    "Du bist YouTube-Skript-Autor fuer Veluera Beauty.\n"
    "Thema: {topic} | Sprache: {lang} | Zielgruppe: {audience}\n"
    "Produkte: {products_json}\n\n"
    "Erstelle ein 10-Min Ranking-Video (energetisch, nicht werbend, hohe Retention).\n"
    "Hook in 15 Sek, offene Loops, Vor- und Nachteile, Ueberraschungsempfehlung, CTA.\n\n"
    "NUR GUELTIGES JSON (kein Markdown, keine Backticks):\n"
    '{{"title":"","thumbnail_text":"","hook":"","intro":"",'
    '"sections":[{{"product_name":"","rank":1,"voiceover":"",'
    '"onscreen_text":[""],"price_display":"EUR XX"}}],'
    '"surprise_pick":{{"product_name":"","voiceover":""}},'
    '"outro":"","youtube_description":"","tags":[""],'
    '"chapters":[{{"time":"0:00","title":"Intro"}}]}}'
)

def generate_script(cfg, products):
    import unicodedata
    
    def clean(text):
        if not text:
            return ""
        # HTML entities und Non-ASCII bereinigen
        text = text.replace("&amp;", "&").replace("&quot;", '"')
        text = text.replace("&#39;", "'").replace("&nbsp;", " ")
        # Nur ASCII behalten
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
        return text.strip()

    prods = [
        {"title": clean(p.get("name", "")),
         "brand": clean(p.get("brand", "")),
         "price": p.get("sale_price", 0),
         "desc":  clean((p.get("description") or ""))[:120]}
        for p in products
    ]
    
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": CLAUDE_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 4000,
              "messages": [{"role": "user", "content": PROMPT.format(
                  topic=clean(cfg["topic"]),
                  lang=cfg["lang"],
                  audience=cfg["audience"],
                  products_json=json.dumps(prods, ensure_ascii=True))}]},
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"].strip()
    if "```" in text:
        for part in text.split("```"):
            p = part.lstrip("json").strip()
            if p.startswith("{"):
                text = p
                break
    return json.loads(text)

# ── 3: ELEVENLABS VOICEOVER ───────────────────
def gen_segment(text, path):
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE}",
        headers={"xi-api-key": EL_KEY, "Content-Type": "application/json"},
        json={"text": text[:2000], "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.4, "similarity_boost": 0.8}},
        timeout=60,
    )
    if r.status_code != 200:
        print(f"  ElevenLabs {r.status_code}: {r.text[:100]}")
        return False
    Path(path).write_bytes(r.content)
    return True

def build_voiceover(script, tmp):
    parts = [("intro", f"{script.get('hook','')} {script.get('intro','')}")]
    for i, s in enumerate(script.get("sections", [])):
        parts.append((f"p{i}", s.get("voiceover", "")))
    sp = script.get("surprise_pick") or {}
    if sp.get("voiceover"):
        parts.append(("surprise", sp["voiceover"]))
    if script.get("outro"):
        parts.append(("outro", script["outro"]))

    segs = []
    for name, text in parts:
        if not text.strip():
            continue
        p = f"{tmp}/seg_{name}.mp3"
        if gen_segment(text, p):
            segs.append(p)
        time.sleep(0.5)

    if not segs:
        return None
    lst = f"{tmp}/list.txt"
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(f"file '{s}'" for s in segs))
    out = f"{tmp}/vo.mp3"
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, out],
        capture_output=True,
    )
    return out if r.returncode == 0 else None

# ── 4: VIDEO (moviepy 2.x) ────────────────────
def fallback_img(path, title):
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (W, H), (26, 26, 46))
        ImageDraw.Draw(img).text(
            (W // 2, H // 2), title[:50], fill=(201, 169, 110), anchor="mm"
        )
        img.save(path, "JPEG")
    except Exception:
        pass

def build_video(script, products, vo_path, tmp):
    sections = script.get("sections", [])
    if not sections:
        return None
    audio   = AudioFileClip(vo_path)
    dur     = audio.duration / len(sections)
    pmap    = {p.get("title", ""): p for p in products}
    clips   = []

    for i, sec in enumerate(sections):
        p    = pmap.get(sec.get("product_name", ""), {})
        path = f"{tmp}/img{i}.jpg"
        if p.get("ean"):
            try:
                r = requests.get(f"{CDN}/{p['ean']}.jpg", timeout=10)
                if r.status_code == 200:
                    Path(path).write_bytes(r.content)
                else:
                    fallback_img(path, sec.get("product_name", ""))
            except Exception:
                fallback_img(path, sec.get("product_name", ""))
        else:
            fallback_img(path, sec.get("product_name", ""))

        base   = ImageClip(path).with_duration(dur).resized((W, H))
        layers = [base]
        try:
            layers.append(
                TextClip(
                    text=f"#{sec.get('rank', i+1)}  {sec.get('product_name', '')}",
                    font_size=54, color="white", font="Liberation-Sans-Bold",
                    stroke_color="black", stroke_width=2,
                ).with_duration(dur).with_position(("center", H - 180))
            )
            layers.append(
                TextClip(
                    text=f"EUR {p.get('sale_price', 0):.2f}",
                    font_size=42, color="#c9a96e", font="Liberation-Sans-Bold",
                ).with_duration(dur).with_position(("center", H - 110))
            )
            ot = sec.get("onscreen_text", [])
            if ot:
                layers.append(
                    TextClip(
                        text=ot[0][:70], font_size=34,
                        color="white", font="Liberation-Sans",
                    ).with_duration(dur).with_position(("center", 70))
                )
        except Exception as e:
            print(f"  TextClip skip {i}: {e}")
        clips.append(CompositeVideoClip(layers, size=(W, H)))

    out = f"{tmp}/final.mp4"
    concatenate_videoclips(clips, method="compose").with_audio(audio).write_videofile(
        out, fps=24, codec="libx264", audio_codec="aac", threads=4, logger=None
    )
    return out

# ── 5: YOUTUBE UPLOAD (OAuth2 Refresh Token) ──
def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=YT_REFRESH,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SEC,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def yt_description(script, products):
    desc = script.get("youtube_description", "") + "\n\n"
    for ch in script.get("chapters", []):
        desc += f"{ch['time']} {ch['title']}\n"
    desc += "\n Produkte aus diesem Video\n"
    for i, p in enumerate(products[:10], 1):
        desc += f"{i}. {p.get('title','')} — EUR {p.get('sale_price',0):.2f}\n"
        desc += f"   {p.get('affiliate_url','')}\n"
    desc += "\nAlle Deals: veluera.beauty\n"
    return desc[:5000]

def upload_yt(vid_path, script, products):
    yt  = get_youtube_client()
    req = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":       script.get("title", "")[:100],
                "description": yt_description(script, products),
                "tags":        script.get("tags", []),
                "categoryId":  "26",
            },
            "status": {
                "privacyStatus":          "public",
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=MediaFileUpload(
            vid_path, chunksize=-1, resumable=True, mimetype="video/mp4"
        ),
    )
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            print(f"  Upload {int(st.progress() * 100)}%")
    return resp.get("id")

# ── 6: LOGGING ────────────────────────────────
def log_job(cfg, status, **kwargs):
    sb.table("video_jobs").insert({
        "topic":    cfg["topic"],
        "category": cfg["category"],
        "lang":     cfg["lang"],
        "status":   status,
        **kwargs,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()

# ── PIPELINE ──────────────────────────────────
def run(cfg):
    print(f"\n{'='*55}\n {cfg['topic']}\n{'='*55}")
    try:
        products = select_products(cfg["category"], cfg.get("max_price", 100))
        assert len(products) >= 5, f"Nur {len(products)} Produkte"
        print(f"  1/5 Produkte: {len(products)}")

        script = generate_script(cfg, products)
        print(f"  2/5 Skript: {script.get('title','')[:55]}")

        with tempfile.TemporaryDirectory() as tmp:
            vo = build_voiceover(script, tmp)
            assert vo, "Voiceover fehlgeschlagen"
            print("  3/5 Voiceover OK")

            vid = build_video(script, products, vo, tmp)
            assert vid, "Video fehlgeschlagen"
            print("  4/5 Video OK")

            vid_id = upload_yt(vid, script, products)
            assert vid_id, "Upload fehlgeschlagen"

        url = f"https://youtube.com/watch?v={vid_id}"
        log_job(cfg, "done", youtube_id=vid_id, video_url=url,
                title=script.get("title", ""),
                published_at=datetime.utcnow().isoformat())
        print(f"  5/5 Fertig: {url}")

    except Exception as e:
        print(f"  FEHLER: {e}")
        log_job(cfg, "error", error_message=str(e))

if __name__ == "__main__":
    hour = datetime.utcnow().hour
    run(TOPICS[hour // 6 % len(TOPICS)])
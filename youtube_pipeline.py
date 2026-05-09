def build_video(script, products, tmp):
    import random
    from pathlib import Path as P
    from PIL import Image, ImageDraw

    sections = script.get("sections", [])
    if not sections:
        return None

    dur_per_slide = 45
    FONT     = "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf"
    FONT_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf" \
               if P("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf").exists() \
               else FONT

    def find_product(name):
        name_lower = name.lower().strip()
        for p in products:
            pn = (p.get("name") or "").lower().strip()
            if pn == name_lower or name_lower in pn or pn in name_lower:
                return p
        return {}

    def process_image(src_path, out_path):
        try:
            img = Image.open(src_path).convert("RGB")
            img_ratio = img.width / img.height
            target_ratio = W / H
            if img_ratio > target_ratio:
                new_h = H
                new_w = int(H * img_ratio)
            else:
                new_w = W
                new_h = int(W / img_ratio)
            img  = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - W) // 2
            top  = (new_h - H) // 2
            img  = img.crop((left, top, left + W, top + H))
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 150))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            img.save(out_path, "JPEG", quality=90)
            return True
        except Exception as e:
            print(f"  Bild-Processing Fehler: {e}")
            return False

    clips = []

    # ── INTRO SLIDE ───────────────────────────
    intro_path = f"{tmp}/intro.jpg"
    fallback_img(intro_path, script.get("title", "Veluera Beauty"))
    intro_base = ImageClip(intro_path).with_duration(15).resized((W, H))
    try:
        intro_layers = [intro_base]
        intro_layers.append(TextClip(
            text=script.get("title", "")[:60],
            font_size=72, color="white", font=FONT,
            stroke_color="black", stroke_width=3,
        ).with_duration(15).with_position(("center", "center")))
        intro_layers.append(TextClip(
            text=script.get("hook", "")[:80],
            font_size=34, color="#c9a96e", font=FONT,
        ).with_duration(15).with_position(("center", H - 150)))
        clips.append(CompositeVideoClip(intro_layers, size=(W, H)))
    except Exception as e:
        print(f"  Intro skip: {e}")
        clips.append(intro_base)

    # ── PRODUKT SLIDES ────────────────────────
    for i, sec in enumerate(sections):
        product_name = sec.get("product_name", "")
        p = find_product(product_name)

        # Bild laden und verarbeiten
        raw_path = f"{tmp}/raw_{i}.jpg"
        img_path = f"{tmp}/img_{i}.jpg"
        img_ok = False
        if p.get("ean"):
            try:
                r = requests.get(f"{CDN}/{p['ean']}.jpg", timeout=10)
                if r.status_code == 200:
                    Path(raw_path).write_bytes(r.content)
                    img_ok = process_image(raw_path, img_path)
            except Exception:
                pass
        if not img_ok:
            fallback_img(img_path, product_name)

        base   = ImageClip(img_path).with_duration(dur_per_slide).resized((W, H))
        layers = [base]

        try:
            rank     = sec.get("rank", i + 1)
            name     = product_name[:50]
            price    = p.get("sale_price", 0)
            brand    = (p.get("brand") or "").upper()
            desc     = (p.get("description") or "")[:100]
            onscreen = sec.get("onscreen_text", [])
            vo_text  = (sec.get("voiceover") or "")[:150]

            # Rang oben links
            layers.append(TextClip(
                text=f"#{rank}",
                font_size=90, color="#c9a96e", font=FONT,
            ).with_duration(dur_per_slide).with_position((60, 50)))

            # Veluera Logo oben rechts
            layers.append(TextClip(
                text="veluera.beauty",
                font_size=28, color="#c9a96e", font=FONT,
            ).with_duration(dur_per_slide).with_position((W - 320, 60)))

            # Produktname
            layers.append(TextClip(
                text=name,
                font_size=62, color="white", font=FONT,
                stroke_color="black", stroke_width=2,
            ).with_duration(dur_per_slide).with_position(("center", H - 320)))

            # Brand
            if brand:
                layers.append(TextClip(
                    text=brand,
                    font_size=32, color="#c9a96e", font=FONT,
                ).with_duration(dur_per_slide).with_position(("center", H - 248)))

            # Preis
            if price and price > 0:
                layers.append(TextClip(
                    text=f"EUR {price:.2f}",
                    font_size=48, color="white", font=FONT,
                    stroke_color="black", stroke_width=1,
                ).with_duration(dur_per_slide).with_position(("center", H - 195)))

            # Onscreen Info
            info = onscreen[0] if onscreen else desc
            if info:
                layers.append(TextClip(
                    text=info[:90],
                    font_size=28, color="white", font=FONT_REG,
                ).with_duration(dur_per_slide).with_position(("center", H - 135)))

            # Voiceover-Text als Untertitel
            if vo_text:
                layers.append(TextClip(
                    text=vo_text,
                    font_size=24, color="#dddddd", font=FONT_REG,
                ).with_duration(dur_per_slide).with_position(("center", H - 75)))

        except Exception as e:
            print(f"  TextClip skip {i}: {e}")

        clips.append(CompositeVideoClip(layers, size=(W, H)))

    # ── OUTRO SLIDE ───────────────────────────
    outro_path = f"{tmp}/outro.jpg"
    fallback_img(outro_path, "veluera.beauty")
    outro_base = ImageClip(outro_path).with_duration(20).resized((W, H))
    try:
        outro_layers = [outro_base]
        outro_layers.append(TextClip(
            text="Alle Deals auf veluera.beauty",
            font_size=64, color="white", font=FONT,
            stroke_color="black", stroke_width=2,
        ).with_duration(20).with_position(("center", H // 2 - 60)))
        outro_layers.append(TextClip(
            text="Jetzt abonnieren fuer taeglich neue Beauty Deals!",
            font_size=36, color="#c9a96e", font=FONT,
        ).with_duration(20).with_position(("center", H // 2 + 40)))
        clips.append(CompositeVideoClip(outro_layers, size=(W, H)))
    except Exception as e:
        print(f"  Outro skip: {e}")
        clips.append(outro_base)

    # ── ZUSAMMENFUEHREN ───────────────────────
    video     = concatenate_videoclips(clips, method="compose")
    total_dur = video.duration

    # Musik
    track_num  = random.randint(1, 6)
    music_path = f"/app/music/Track_{track_num}.mp3"
    try:
        music = AudioFileClip(music_path).with_effects([afx.MultiplyVolume(0.3)])
        if music.duration < total_dur:
            from moviepy import concatenate_audioclips
            loops = int(total_dur / music.duration) + 1
            music = concatenate_audioclips([music] * loops)
        music = music.subclipped(0, total_dur)
        video = video.with_audio(music)
    except Exception as e:
        print(f"  Musik skip: {e}")

    out = f"{tmp}/final.mp4"
    video.write_videofile(
        out, fps=24, codec="libx264",
        audio_codec="aac", threads=4, logger=None
    )
    return out
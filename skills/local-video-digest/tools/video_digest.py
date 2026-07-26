# -*- coding: utf-8 -*-
"""
local-video-digest: видео (.MOV/.mp4 и т.п.) -> контактный лист кадров (с таймкодами)
+ транскрипт речи (faster-whisper) -> digest.md. Чтобы Codex получал и картинку, и
КОНТЕКСТ из закадрового пояснения, а не только кадры без смысла.

Использование:
  python video_digest.py <video> [--out DIR] [--model small|medium|large-v3]
                         [--frames N] [--mode scene|interval] [--scene-threshold F]
                         [--lang ru] [--device auto|cuda|cpu] [--no-audio]
  Кадры: по умолчанию mode=scene (PySceneDetect ContentDetector, кадр из середины
  каждой сцены — ловит момент смены плана; при <3 сцен откат на равные интервалы).
Выход в DIR: contact_sheet.jpg, transcript.md, digest.md (+ frames/, audio.wav)
Зависимости: ffmpeg (C:\\ProgramData\\ORG-tools\\ffmpeg\\bin или PATH), faster-whisper, Pillow.
"""
import os, sys, subprocess, argparse, math, shutil, json

FFDIR = r"C:\ProgramData\ORG-tools\ffmpeg\bin"
def tool(name):
    p = os.path.join(FFDIR, name+".exe")
    if os.path.isfile(p): return p
    f = shutil.which(name)
    if f: return f
    sys.exit(f"[ERR] {name} не найден (ни {FFDIR}, ни PATH)")
FFMPEG, FFPROBE = tool("ffmpeg"), tool("ffprobe")

def run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")

def probe(video):
    r = run([FFPROBE,"-v","error","-select_streams","v:0","-show_entries",
             "stream=width,height,duration","-show_entries","format=duration",
             "-of","json",video])
    j = json.loads(r.stdout or "{}")
    st = (j.get("streams") or [{}])[0]
    dur = float(st.get("duration") or j.get("format",{}).get("duration") or 0)
    return int(st.get("width",0)), int(st.get("height",0)), dur

def mmss(t): return f"{int(t//60):02d}:{int(t%60):02d}"

def extract_frames(video, dur, n, outdir):
    fdir = os.path.join(outdir,"frames"); os.makedirs(fdir, exist_ok=True)
    times = [dur*(i+0.5)/n for i in range(n)]
    files = []
    for i,t in enumerate(times):
        fp = os.path.join(fdir, f"f{i:03d}.jpg")
        run([FFMPEG,"-y","-loglevel","error","-ss",f"{t:.2f}","-i",video,
             "-frames:v","1","-q:v","3",fp])
        if os.path.isfile(fp): files.append((t,fp))
    return files

def detect_scenes(video, threshold):
    """Границы сцен через PySceneDetect ContentDetector -> [(start_s,end_s)]. [] при недоступности/ошибке."""
    try:
        from scenedetect import detect, ContentDetector
    except Exception:
        print("[warn] scenedetect не установлен -> интервал"); return []
    try:
        scenes = detect(video, ContentDetector(threshold=threshold))
        return [(s.get_seconds(), e.get_seconds()) for s,e in scenes]
    except Exception as e:
        print(f"[warn] scenedetect не сработал ({e}) -> интервал"); return []

def extract_frames_scenes(video, dur, outdir, threshold, min_len=1.5, cap=40):
    """Кадр из СЕРЕДИНЫ каждой сцены (камера уже стабилизировалась на объекте).
    Возвращает [] если сцен <3 (тогда main откатится на интервал)."""
    scenes = [(s,e) for (s,e) in detect_scenes(video, threshold) if e-s >= min_len]
    if len(scenes) < 3: return []
    mids = [(s+e)/2 for (s,e) in scenes]
    if len(mids) > cap:                         # слишком дробно -> проредить равномерно
        step = len(mids)/cap
        mids = [mids[int(i*step)] for i in range(cap)]
    fdir = os.path.join(outdir,"frames"); os.makedirs(fdir, exist_ok=True)
    files=[]
    for i,t in enumerate(mids):
        fp = os.path.join(fdir, f"s{i:03d}.jpg")
        run([FFMPEG,"-y","-loglevel","error","-ss",f"{t:.2f}","-i",video,
             "-frames:v","1","-q:v","3",fp])
        if os.path.isfile(fp): files.append((t,fp))
    return files

def contact_sheet(frames, outpath, tile_w=300):
    from PIL import Image, ImageDraw, ImageFont
    if not frames: return None
    cap = 26
    imgs = []
    for t,fp in frames:
        im = Image.open(fp).convert("RGB")
        w,h = im.size; tw = tile_w; th = int(h*tw/w)
        im = im.resize((tw,th))
        canvas = Image.new("RGB",(tw,th+cap),(0,0,0))
        canvas.paste(im,(0,0))
        d = ImageDraw.Draw(canvas)
        try: font = ImageFont.truetype("arial.ttf", 18)
        except: font = ImageFont.load_default()
        d.text((6,th+3), mmss(t), fill=(255,255,0), font=font)
        imgs.append(canvas)
    cols = min(5, len(imgs)); rows = math.ceil(len(imgs)/cols)
    cw = imgs[0].width; ch = imgs[0].height
    sheet = Image.new("RGB",(cols*cw, rows*ch),(20,20,20))
    for k,im in enumerate(imgs):
        r,c = divmod(k,cols); sheet.paste(im,(c*cw, r*ch))
    sheet.save(outpath, quality=88)
    return outpath

def transcribe(wav, model_name, lang, device):
    from faster_whisper import WhisperModel
    order = ([("cuda","float16"),("cpu","int8")] if device=="auto"
             else [("cuda","float16")] if device=="cuda" else [("cpu","int8")])
    last=None
    for dev,ct in order:
        try:
            m = WhisperModel(model_name, device=dev, compute_type=ct)
            segs,info = m.transcribe(wav, language=lang, vad_filter=True)
            segs = list(segs)
            return segs, info, dev
        except Exception as e:
            last=e; continue
    raise last

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="small")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--mode", default="scene", choices=["scene","interval"])
    ap.add_argument("--scene-threshold", type=float, default=27.0, dest="scene_threshold")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    video = os.path.abspath(a.video)
    out = a.out or os.path.splitext(video)[0]+"_digest"
    os.makedirs(out, exist_ok=True)
    w,h,dur = probe(video)
    frames = []
    if a.mode == "scene":
        frames = extract_frames_scenes(video, dur, out, a.scene_threshold)
        if frames:
            print(f"[i] {os.path.basename(video)}  {w}x{h}  {dur:.1f}s  -> {len(frames)} кадров (по сценам)")
        else:
            print("[i] сцен <3 или scenedetect недоступен -> откат на интервал")
    if not frames:
        n = a.frames or max(9, min(30, round(dur/5)))
        print(f"[i] {os.path.basename(video)}  {w}x{h}  {dur:.1f}s  -> {n} кадров (интервал)")
        frames = extract_frames(video, dur, n, out)
    sheet = contact_sheet(frames, os.path.join(out,"contact_sheet.jpg"))
    print(f"[i] контактный лист: {sheet} ({len(frames)} кадров)")
    tr_md = os.path.join(out,"transcript.md"); tr_lines=[]
    dev_used="-"
    if not a.no_audio:
        wav = os.path.join(out,"audio.wav")
        run([FFMPEG,"-y","-loglevel","error","-i",video,"-vn","-ar","16000","-ac","1",wav])
        print(f"[i] аудио извлечено, расшифровка ({a.model})...")
        segs,info,dev_used = transcribe(wav, a.model, a.lang, a.device)
        for s in segs: tr_lines.append(f"[{mmss(s.start)}] {s.text.strip()}")
        with open(tr_md,"w",encoding="utf-8") as f:
            f.write(f"# Транскрипт: {os.path.basename(video)}\n\n")
            f.write(f"*model={a.model}, device={dev_used}, lang={getattr(info,'language',a.lang)}*\n\n")
            f.write("\n".join(tr_lines) if tr_lines else "_(речь не распознана / нет звука)_")
        print(f"[i] транскрипт: {tr_md} ({len(tr_lines)} сегментов, device={dev_used})")
    # digest
    with open(os.path.join(out,"digest.md"),"w",encoding="utf-8") as f:
        f.write(f"# Дайджест видео: {os.path.basename(video)}\n\n")
        f.write(f"- Разрешение: {w}x{h}, длительность: {mmss(dur)} ({dur:.1f}s)\n")
        f.write(f"- Кадры: contact_sheet.jpg ({len(frames)} шт, таймкоды на каждом)\n")
        f.write(f"- Транскрипт: transcript.md\n\n")
        f.write("## Речь (закадровое пояснение)\n\n")
        f.write("\n".join(tr_lines) if tr_lines else "_(нет)_")
    print(f"[OK] digest: {os.path.join(out,'digest.md')}")

if __name__ == "__main__":
    main()

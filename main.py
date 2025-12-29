import os, subprocess, asyncio, zipfile, re
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("8590905884:AAGUQ-pKMBmQY82iHNNHrxROGgoKM8uRm_0")
ADMIN_IDS = list(map(int, os.getenv("7129426550", "").split(",")))

BASE_DIR = "downloads"
os.makedirs(BASE_DIR, exist_ok=True)

SUBJECT_RULES = {
    "Digital_Electronics": [
        "Digital", "Logic", "Gate", "K-map", "ADC", "DAC", "Flip", "Counter"
    ],
    "Design_Analysis_of_Algorithm": [
        "Algorithm", "DP", "Greedy", "Graph", "NP", "Heap", "Sort"
    ],
    "Operating_Systems": [
        "Process", "Thread", "Deadlock", "Scheduling", "Memory", "Paging", "Disk"
    ],
    "Computer_Architecture": [
        "CPU", "Cache", "Pipeline", "Architecture", "Register", "Instruction"
    ],
    "Discrete_Mathematics": [
        "Set", "Relation", "Logic", "Lattice", "Graph Theory"
    ]
}

def is_admin(uid):
    return uid in 7129426550

def detect_subject(text):
    for subject, keywords in SUBJECT_RULES.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                return subject
    return "Miscellaneous"

def detect_module(text):
    match = re.match(r"(M\d+)", text.strip())
    return match.group(1) if match else "MISC"

def progress_bar(p):
    blocks = int(p / 10)
    return "█" * blocks + "░" * (10 - blocks)

async def handle_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Private bot")
        return

    doc = update.message.document
    status = await update.message.reply_text("📂 Initializing...")

    file = await context.bot.get_file(doc.file_id)
    txt_path = os.path.join(BASE_DIR, doc.file_name)
    await file.download_to_drive(txt_path)

    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [l for l in f if ".m3u8" in l]

    total = len(lines)
    done = failed = 0
    processed = 0
    index = {}

    for line in lines:
        processed += 1
        try:
            title, url = line.split(":", 1)
            subject = detect_subject(title)
            module = detect_module(title)

            safe_title = title.replace(" ", "_").replace("/", "")
            subject_dir = os.path.join(BASE_DIR, subject, module)
            os.makedirs(subject_dir, exist_ok=True)

            out = os.path.join(subject_dir, f"{safe_title}.mp4")

            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", url.strip(),
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                out
            ]

            await asyncio.to_thread(subprocess.run, cmd, timeout=300)

            await update.message.reply_video(video=open(out, "rb"), caption=safe_title)

            index.setdefault((subject, module), []).append(url.strip())
            done += 1

        except Exception:
            failed += 1

        percent = int((processed / total) * 100)
        await status.edit_text(
            f"📚 Subject: {subject}\n"
            f"🧩 Module: {module}\n"
            f"🎬 Video: {safe_title[:40]}\n\n"
            f"{progress_bar(percent)} {percent}%\n\n"
            f"✔ Success: {done}\n"
            f"❌ Failed: {failed}"
        )

    # PLAYLIST + ZIP
    for (subject, module), urls in index.items():
        mdir = os.path.join(BASE_DIR, subject, module)

        pl = os.path.join(mdir, "playlist.m3u8")
        with open(pl, "w") as p:
            for u in urls:
                p.write(u + "\n")

        zip_path = f"{mdir}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(mdir):
                z.write(os.path.join(mdir, f), arcname=f)

        await update.message.reply_document(
            document=open(zip_path, "rb"),
            caption=f"📦 {subject} - {module}"
        )

    await status.edit_text("✅ ALL SUBJECTS COMPLETED")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.ALL, handle_txt))
    await app.run_polling()

if name == "main":
    asyncio.run(main())

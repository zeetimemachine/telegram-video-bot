pip install -r requirements.txtimport os
import re
import time
import logging
import subprocess
import shutil
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURATION ---
BOT_TOKEN = "8590905884:AAGUQ-pKMBmQY82iHNNHrxROGgoKM8uRm_0"
ADMIN_ID = 7129426550  # Replace with your numeric Telegram ID
DOWNLOAD_DIR = "downloads"

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ADMIN CHECK DECORATOR ---
def restricted(func):
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ Unauthorized access. This is a private bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- HELPER: PROGRESS BAR ---
async def progress_callback(current, total, message, last_edit_time):
    # Only update every 3 seconds to avoid hitting Telegram API limits
    if time.time() - last_edit_time[0] > 3:
        percent = (current / total) * 100
        try:
            await message.edit_text(f"📤 Uploading: {percent:.1f}% complete")
            last_edit_time[0] = time.time()
        except Exception:
            pass

# --- HELPER: FFMPEG DOWNLOADER ---
def download_m3u8(url, filename):
    """Downloads m3u8 and converts to mp4 using system FFmpeg"""
    output_path = os.path.join(DOWNLOAD_DIR, f"{filename}.mp4")
    
    # FFmpeg command to download stream without re-encoding (copy codec) for speed
    cmd = [
        'ffmpeg', '-y', '-i', url, 
        '-bsf:a', 'aac_adtstoasc', 
        '-vcodec', 'copy', 
        '-c', 'copy', 
        '-crf', '50', 
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path
    except subprocess.CalledProcessError:
        return None

# --- MAIN LOGIC: PROCESS TXT FILE ---
@restricted
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    # Check if it is a text file
    if not document.mime_type.startswith("text"):
        await update.message.reply_text("Please send a valid .txt file.")
        return

    status_msg = await update.message.reply_text("📂 Processing file...")
    
    # Download the text file
    file_info = await document.get_file()
    file_path = f"{document.file_name}"
    await file_info.download_to_drive(file_path)

    # Parse content
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex to find "Title:URL" format from your specific file
    # Matches: "M01 L-01 Digital Signal:https://..."
    pattern = re.compile(r'^(.*?):(https?://.*\.m3u8)$', re.MULTILINE)
    matches = pattern.findall(content)

    if not matches:
        await status_msg.edit_text("❌ No valid links found in the format Title:URL.")
        return

    await status_msg.edit_text(f"✅ Found {len(matches)} videos. Starting processing...")
    
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    # Dictionary to hold file paths for zipping modules later
    module_map = {} 

    for title, url in matches:
        clean_title = title.strip().replace("/", "-") # Sanitize filename
        
        # 1. Detect Module for Folder Logic (e.g., extract "M01")
        module_match = re.search(r'(M\d+)', clean_title)
        module_name = module_match.group(1) if module_match else "Misc"
        
        if module_name not in module_map:
            module_map[module_name] = []

        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⬇️ Downloading: {clean_title}")

# 2. Download via FFmpeg
        file_path = download_m3u8(url, clean_title)
        
        if file_path and os.path.exists(file_path):
            module_map[module_name].append(file_path)
            
            # 3. Upload to Telegram
            upload_msg = await context.bot.send_message(chat_id=ADMIN_ID, text="📤 Starting upload...")
            last_time = [time.time()]
            
            try:
                await context.bot.send_video(
                    chat_id=ADMIN_ID,
                    video=open(file_path, 'rb'),
                    caption=f"🎥 {clean_title}",
                    parse_mode="Markdown",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=120,
                    pool_timeout=120,
                    progress=progress_callback,
                    progress_args=(upload_msg, last_time)
                )
                await upload_msg.delete()
            except Exception as e:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Upload Failed: {e}")
            
            # Note: We don't delete the file yet if we want to ZIP it later
        else:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Download Failed for {clean_title}")

    # --- ZIP LOGIC ---
    await context.bot.send_message(chat_id=ADMIN_ID, text="📦 Creating Module ZIPs...")
    
    for module, files in module_map.items():
        if not files: continue
        
        zip_name = f"{module}_Complete.zip"
        # create a zip file
        # (Implementation of zip creation using zipfile library goes here)
        # shutil.make_archive would be easier if files were in folders
        
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"✅ {module} processing complete (ZIP feature placeholder).")

        # Cleanup files for this module
        for f in files:
            if os.path.exists(f):
                os.remove(f)

    await context.bot.send_message(chat_id=ADMIN_ID, text="🎉 All tasks completed!")

if name == 'main':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), handle_document))
    
    print("Bot is running...")
    app.run_polling()

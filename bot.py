import os
import re
import logging
import asyncio
import subprocess
import shutil
import time
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler

# ================= CONFIGURATION =================
# These are loaded from Railway Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Convert Admin ID to integer (if set), otherwise 0
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
except ValueError:
    print("⚠️ ADMIN_ID is not a valid number. Admin checks will fail.")
    ADMIN_ID = 0

DOWNLOAD_DIR = "downloads"
# =================================================

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(name)

# --- HELPER: RESTRICT ACCESS ---
def restricted(func):
    """Decorator to ensure only the Admin uses the bot."""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if ADMIN_ID != 0 and user_id != ADMIN_ID:
            await update.message.reply_text("⛔ Unauthorized Access. This is a private bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- HELPER: PROGRESS BAR FOR UPLOAD ---
async def upload_progress(current, total, message, last_update_time):
    """Updates the Telegram message with upload percentage."""
    now = time.time()
    # Update only every 5 seconds to avoid flooding API (Telegram limit)
    if now - last_update_time[0] > 5:
        percent = (current / total) * 100
        try:
            await message.edit_text(f"📤 Uploading: {percent:.1f}%")
            last_update_time[0] = now
        except Exception:
            pass # Ignore errors if message was deleted

# --- HELPER: VIDEO DOWNLOADER (FFMPEG) ---
def download_m3u8_sync(url, output_path):
    """
    Runs FFmpeg to convert m3u8 to mp4.
    Returns True if successful, False otherwise.
    """
    command = [
        'ffmpeg',
        '-y',                 # Overwrite output file
        '-i', url,            # Input URL
        '-bsf:a', 'aac_adtstoasc', # Fix audio bitstream for MP4
        '-c', 'copy',         # Copy codec (Fastest, no re-encoding)
        output_path           # Output file
    ]
    
    try:
        # Run ffmpeg and hide the huge console output
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

# --- MAIN COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome Boss!\n\n"
        "Send me a .txt file containing Title:URL lines.\n"
        "I will download them, organize by Module (M01, M02...), zip them, and send them back.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

@restricted
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    # 1. Validate File
    if not document.mime_type.startswith("text") and not document.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Please send a valid .txt file.")
        return

    status_msg = await update.message.reply_text("📂 analyzing file...")
    
    # 2. Download the Text File
    file_path = f"temp_{document.file_name}"
    new_file = await document.get_file()
    await new_file.download_to_drive(file_path)

    # 3. Parse Content
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Extract Title and URL using Regex
    # Matches: "Any Title Here:https://link.m3u8"
    pattern = re.compile(r'^(.*?):(https?://.*\.m3u8)$', re.MULTILINE)
    matches = pattern.findall(content)

    if not matches:
        await status_msg.edit_text("❌ No valid Title:URL lines found.")
        os.remove(file_path)
        return

await status_msg.edit_text(f"✅ Found {len(matches)} videos. Starting processing...")
    
    # Create Downloads Folder
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR) # Clean start
    os.makedirs(DOWNLOAD_DIR)

    # Group by Module (M01, M02, etc.)
    # Structure: module_map = { "M01": [ ("Title", "Path"), ... ], "M02": ... }
    module_map = {}

    for title, url in matches:
        clean_title = title.strip().replace("/", "-").replace("\\", "-")
        
        # Detect Module Name (e.g., M01 from "M01 L-01...")
        mod_match = re.search(r'(M\d+)', clean_title)
        module_name = mod_match.group(1) if mod_match else "Uncategorized"
        
        # Create Module Folder
        mod_path = os.path.join(DOWNLOAD_DIR, module_name)
        os.makedirs(mod_path, exist_ok=True)
        
        # Define Output Path
        output_filename = f"{clean_title}.mp4"
        output_path = os.path.join(mod_path, output_filename)
        
        # Initialize list if new module
        if module_name not in module_map:
            module_map[module_name] = []
        
        # Add to processing queue
        module_map[module_name].append({
            "title": clean_title,
            "url": url,
            "path": output_path,
            "filename": output_filename
        })

    os.remove(file_path) # Cleanup input file

    # --- PROCESS EACH MODULE ---
    for module, videos in module_map.items():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"🏗 Starting Module: {module} ({len(videos)} videos)"
        )
        
        downloaded_files = []

        # A. Download Loop
        for vid in videos:
            msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⬇️ Downloading: {vid['title']}...", parse_mode="Markdown")
            
            # Run FFmpeg in a separate thread to keep bot responsive
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, download_m3u8_sync, vid['url'], vid['path'])
            
            if success:
                # B. Upload Video
                await msg.edit_text("📤 Uploading...")
                last_time = [time.time()]
                try:
                    with open(vid['path'], 'rb') as video_file:
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=video_file,
                            caption=f"🎥 {vid['title']}",
                            width=1280, height=720, # Optional: assumes 720p
                            supports_streaming=True,
                            read_timeout=300, 
                            write_timeout=300,
                            pool_timeout=300,
                            progress=upload_progress,
                            progress_args=(msg, last_time)
                        )
                    await msg.delete() # Clean up status message
                    downloaded_files.append(vid['path'])
                except Exception as e:
                    await msg.edit_text(f"❌ Upload Error: {e}")
            else:
                await msg.edit_text("❌ Download Failed (Stream might be dead).")

        # C. Create ZIP for Module
        if downloaded_files:
            zip_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🤐 Zipping Module {module}...")
            
            zip_filename = f"{module}_Complete.zip"
            zip_path = os.path.join(DOWNLOAD_DIR, zip_filename)
            
            # Create ZIP
            shutil.make_archive(zip_path.replace('.zip', ''), 'zip', os.path.join(DOWNLOAD_DIR, module))
            
            # Upload ZIP
            try:
                await zip_msg.edit_text(f"📤 Uploading {zip_filename}...")
                with open(zip_path, 'rb') as zip_file:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=zip_file,
                        caption=f"📦 {module} Complete Module",
                        read_timeout=600,
                        write_timeout=600
                    )
                await zip_msg.delete()
            except Exception as e:
                await zip_msg.edit_text(f"❌ ZIP Upload Failed (File might be too big for bot): {e}")

        # D. Cleanup Module Folder
        shutil.rmtree(os.path.join(DOWNLOAD_DIR, module))

    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ All Tasks Completed Successfully!")
    
    # Final Cleanup
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)

if name == 'main':
    # Startup Checks
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN is missing from Environment Variables.")
        exit(1)
        
    print(f"🤖 Bot Started. Admin ID: {ADMIN_ID}")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document, handle_document))
    
    print("🚀 Polling...")
    app.run_polling()

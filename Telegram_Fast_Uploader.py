import os
import re
import sys
import signal
import argparse
import ffmpeg
import mimetypes
from tqdm import tqdm
from telethon import TelegramClient, utils
from telethon.tl.types import InputMediaUploadedDocument, DocumentAttributeVideo, DocumentAttributeFilename
from FastTelethon import upload_file

api_id = ''
api_hash = ''
session_file = 'session_name'
chat_id = -1001234567891

# Initialize the Telegram client
client = TelegramClient(session_file, api_id, api_hash)

# Set of uploaded files to avoid duplicates
uploaded_files = set()

# Streamable video formats
STREAMABLE_VIDEO_FORMATS = {
    '.mp4', '.mov', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v', '.3gp', '.3g2',
    '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.flv', '.f4v', '.asf', '.wmv'
}

def remove_extension(filename):
    """Remove file extension from the filename."""
    return os.path.splitext(filename)[0]

def natural_sort_key(s):
    """Natural sorting key for filenames."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

def create_thumbnail(input_video, output_thumb, max_size=320):
    """Create a thumbnail for a video file while maintaining aspect ratio."""
    try:
        probe = ffmpeg.probe(input_video)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if video_stream is None:
            print(f'No video stream found in {input_video}')
            return None

        width = int(video_stream['width'])
        height = int(video_stream['height'])

        # Calculate scaling factor to fit within max_size
        scale = min(max_size / width, max_size / height)
        new_width = int(width * scale)
        new_height = int(height * scale)

        (ffmpeg
         .input(input_video, ss=1)
         .filter('scale', new_width, new_height)
         .output(output_thumb, vframes=1)
         .overwrite_output()
         .run(quiet=True))
        return output_thumb
    except ffmpeg.Error as e:
        print(f'Error creating thumbnail: {e}')
        return None

def is_streamable_video(file_path):
    """
    Check if the file is a video format that's likely to be streamable on Telegram.
    """
    ext = os.path.splitext(file_path)[1].lower()
    mime_type, _ = mimetypes.guess_type(file_path)
    return ext in STREAMABLE_VIDEO_FORMATS or (mime_type and mime_type.startswith('video/'))

async def upload_file_fast(file_path, progress_callback):
    """Upload a single file using FastTelethon."""
    with open(file_path, 'rb') as file:
        return await upload_file(client, file, progress_callback=progress_callback)

async def upload_file_with_progress(file_path, current_file=0, total_files=0):
    """Upload a single file to the Telegram channel with progress bar using FastTelethon."""
    try:
        file_size = os.path.getsize(file_path)
        progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc=f'Uploading {os.path.basename(file_path)} [{current_file}/{total_files}]')

        def progress_callback(current, total):
            progress_bar.update(current - progress_bar.n)

        file = await upload_file_fast(file_path, progress_callback)

        attributes, mime_type = utils.get_attributes(file_path)
        
        is_video = is_streamable_video(file_path)
        
        if is_video:
            # Get video metadata
            probe = ffmpeg.probe(file_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if video_stream:
                width = int(video_stream['width'])
                height = int(video_stream['height'])
                duration = int(float(video_stream['duration']))
            else:
                width, height, duration = 0, 0, 0

            # Create video attribute
            video_attribute = DocumentAttributeVideo(
                w=width,
                h=height,
                duration=duration,
                supports_streaming=True
            )
            
            # Add or replace video attribute
            attributes = [attr for attr in attributes if not isinstance(attr, DocumentAttributeVideo)]
            attributes.append(video_attribute)

        # Always add a filename attribute
        filename_attribute = DocumentAttributeFilename(os.path.basename(file_path))
        attributes = [attr for attr in attributes if not isinstance(attr, DocumentAttributeFilename)]
        attributes.append(filename_attribute)

        media = InputMediaUploadedDocument(
            file=file,
            mime_type=mime_type,
            attributes=attributes,
            thumb=await client.upload_file(create_thumbnail(file_path, 'thumb.jpg')) if is_video else None,
            force_file=False
        )

        message = await client.send_file(
            chat_id,
            media,
            caption=remove_extension(os.path.basename(file_path)),
            supports_streaming=is_video
        )

        progress_bar.close()
        print(f'Successfully uploaded: {file_path}')
        return message
    except Exception as e:
        progress_bar.close()
        print(f'Failed to upload {file_path}: {e}')
        return None

async def send_message(message, bold=False):
    """Send a message to the Telegram channel."""
    try:
        if bold:
            message = f"**{message}**"
        await client.send_message(chat_id, message, parse_mode='Markdown')
    except Exception as e:
        print(f'Failed to send message: {e}')

async def process_directory(dir_path, relative_path, total_files, current_file=0):
    """Process a single directory, uploading its files and subdirectories in order."""
    # Send folder name (except for root folder)
    if relative_path:
        await send_message(relative_path, bold=False)

    # Get and sort files and directories
    items = os.listdir(dir_path)
    files = [f for f in items if os.path.isfile(os.path.join(dir_path, f))]
    dirs = [d for d in items if os.path.isdir(os.path.join(dir_path, d))]
    
    files.sort(key=natural_sort_key)
    dirs.sort(key=natural_sort_key)

    # Process files
    for file in files:
        if file != 'thumb.jpg':
            file_path = os.path.join(dir_path, file)
            if file_path not in uploaded_files:
                print(f'Processing: {file_path}')
                
                current_file += 1
                message = await upload_file_with_progress(file_path, current_file, total_files)

                if message:
                    uploaded_files.add(file_path)
            else:
                print(f'Skipping already uploaded file: {file_path}')
                current_file += 1

    # Process subdirectories
    for dir_name in dirs:
        subdir_path = os.path.join(dir_path, dir_name)
        subdir_relative_path = os.path.join(relative_path, dir_name) if relative_path else dir_name
        current_file = await process_directory(subdir_path, subdir_relative_path, total_files, current_file)

    return current_file

def count_files(directory):
    """Count the total number of files in the directory and its subdirectories."""
    return sum(len(files) for _, _, files in os.walk(directory))

async def upload_files(file_folder):
    if not await client.is_user_authorized():
        print("First time authentication required.")
        phone = input("Please enter your phone number (with country code): ")
        await client.start(phone=phone)
        print("New session created. You may need to enter the code you received.")
        if not await client.is_user_authorized():
            print("Authentication failed. Please run the script again.")
            return

    try:
        await client.get_entity(chat_id)
    except Exception as e:
        print(f"Failed to resolve the chat ID: {e}")
        return

    # Send the top folder name as the title
    await send_message(os.path.basename(file_folder), bold=True)

    total_files = count_files(file_folder)
    print(f"Total files to upload: {total_files}")
    
    # Start processing from the root folder
    await process_directory(file_folder, "", total_files)

def signal_handler(sig, frame):
    print('Stopping the upload process gracefully...')
    client.disconnect()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload files from a specified folder to Telegram.")
    parser.add_argument("folder", help="Path to the folder containing files to upload")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"Error: {args.folder} is not a valid directory")
        sys.exit(1)

    with client:
        client.loop.run_until_complete(upload_files(args.folder))
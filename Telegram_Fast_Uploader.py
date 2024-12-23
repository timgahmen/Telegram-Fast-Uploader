import os
import re
import sys
import signal
import argparse
import asyncio
import ffmpeg
import shutil
import subprocess
import mimetypes
from tqdm import tqdm
from telethon import TelegramClient, utils
from telethon.tl.types import InputMediaUploadedDocument, DocumentAttributeVideo, DocumentAttributeFilename
from FastTelethon import upload_file

# Constants
API_ID = ''
API_HASH = ''
SESSION_FILE = 'session_name'
STREAMABLE_VIDEO_FORMAT = '.mp4'
SIZE_LIMIT_2GB = 2 * 1024 * 1024 * 1024
SIZE_LIMIT_4GB = 4 * 1024 * 1024 * 1024

class TelegramUploader:
    def __init__(self):
        self.client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
        self.uploaded_files = set()

    async def list_chats(self):
        """List all available chats and their IDs without requiring a chat ID input."""
        # Start the client
        await self.client.start()
        
        if not await self.client.is_user_authorized():
            phone = input("Please enter your phone number (with country code): ")
            await self.client.start(phone)
            print("You may need to enter the verification code you receive.")
        
        print("\nFetching your chats...\n")
        print("-" * 70)
        print(f"{'Chat Name':<50} | {'Chat ID':<15}")
        print("-" * 70)
        
        async for dialog in self.client.iter_dialogs():
            name = dialog.name or "Unnamed chat"
            # Truncate long names and ensure proper spacing
            name = name[:47] + "..." if len(name) > 47 else name
            print(f"{name:<50} | {dialog.id:<15}")
        
        print("-" * 70)
    
    @staticmethod
    def remove_extension(filename):
        return os.path.splitext(filename)[0]

    @staticmethod
    def natural_sort_key(s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

    @staticmethod
    def create_thumbnail(input_video, output_thumb, max_size=320):
        try:
            probe = ffmpeg.probe(input_video)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if video_stream is None:
                print(f'No video stream found in {input_video}')
                return None

            width, height = int(video_stream['width']), int(video_stream['height'])
            scale = min(max_size / width, max_size / height)
            new_width, new_height = int(width * scale), int(height * scale)

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

    @staticmethod
    def is_streamable_video(file_path):
        ext = os.path.splitext(file_path)[1].lower()
        mime_type, _ = mimetypes.guess_type(file_path)
        return ext == STREAMABLE_VIDEO_FORMAT and mime_type and mime_type.startswith('video/')

    @staticmethod
    def is_video_file(file_path):
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type and mime_type.startswith('video/')

    @staticmethod
    def check_file_issues(folder_path):
        non_streamable_videos = []
        files_exceeding_2gb = []
        files_exceeding_4gb = []

        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_size = os.path.getsize(file_path)

                if TelegramUploader.is_video_file(file_path) and not TelegramUploader.is_streamable_video(file_path):
                    non_streamable_videos.append(file_path)

                if file_size > SIZE_LIMIT_4GB:
                    files_exceeding_4gb.append(file_path)
                elif file_size > SIZE_LIMIT_2GB:
                    files_exceeding_2gb.append(file_path)

        return non_streamable_videos, files_exceeding_2gb, files_exceeding_4gb

    @staticmethod
    def check_for_gpu():
        try:
            result = subprocess.run(['nvidia-smi'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def get_subtitle_tracks(input_file):
        try:
            probe = ffmpeg.probe(input_file)
            subtitle_tracks = [stream for stream in probe['streams'] if stream['codec_type'] == 'subtitle']
            return subtitle_tracks
        except ffmpeg.Error as e:
            # logging.error(f"Error getting subtitle tracks: {e}")
            return []

    def choose_subtitle(self, input_file):
        subtitle_tracks = self.get_subtitle_tracks(input_file)
        if not subtitle_tracks:
            print("No subtitle tracks found in the video.")
            return None

        print("Available subtitle tracks:")
        for i, track in enumerate(subtitle_tracks):
            print(f"{i + 1}. {track.get('tags', {}).get('language', 'Unknown')} - {track.get('tags', {}).get('title', 'Untitled')}")

        while True:
            choice = input("Enter the number of the subtitle track to burn (or 0 to skip): ")
            if choice.isdigit():
                choice = int(choice)
                if 0 <= choice <= len(subtitle_tracks):
                    return subtitle_tracks[choice - 1]['index'] if choice > 0 else None
            print("Invalid choice. Please try again.")

    def extract_subtitle(input_file, subtitle_index, output_srt):
        try:
            command = [
                'ffmpeg',
                '-i', input_file,
                '-map', f'0:{subtitle_index}',
                output_srt
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            return False
    
    @staticmethod
    def choose_quality():
        while True:
            print("Choose video quality:")
            print("1. Low (720p)")
            print("2. Medium (1080p)")
            print("3. High (Original)")
            choice = input("Enter your choice (1-3): ")
            if choice in ['1', '2', '3']:
                return ['720p', '1080p', 'original'][int(choice) - 1]
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")

    @staticmethod
    def convert_to_mp4(input_file, output_file, quality='original', subtitle_index=None):
            if os.path.exists(output_file):
                action = input(f"Output file {output_file} already exists. (O)verwrite, (B)ackup, or (S)kip? ").lower()
                if action == 'b':
                    backup_dir = os.path.join(os.path.dirname(output_file), 'backups')
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_file = os.path.join(backup_dir, os.path.basename(output_file))
                    shutil.move(output_file, backup_file)
                    print(f"Backed up existing file to {backup_file}")
                elif action == 's':
                    print(f"Skipping conversion of {input_file}")
                    return True

            # Get video information
            probe = ffmpeg.probe(input_file)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if not video_stream:
                return False

            # Determine if we should use GPU acceleration
            use_gpu = TelegramUploader.check_for_gpu()
            if use_gpu:
                vcodec = 'hevc_nvenc'
                preset = 'p7'  # A high-quality preset for NVENC
            else:
                vcodec = 'libx265'
                preset = 'slow'  # A high-quality preset for CPU encoding

            # Prepare FFmpeg command
            output_args = {
                'vcodec': vcodec,
                'acodec': 'aac',
                'preset': preset
            }

            # Handle subtitle burning
            if subtitle_index is not None:
                subtitle_file = f"{os.path.splitext(input_file)[0]}_subtitle.srt"
                if TelegramUploader.extract_subtitle(input_file, subtitle_index, subtitle_file):
                    # Use the extracted subtitle file
                    output_args['vf'] = output_args.get('vf', '') + f",subtitles='{subtitle_file}'"
                    output_args['vf'] = output_args['vf'].lstrip(',')
                else:
                    subtitle_index = None
            
            # Set quality-specific parameters
            if quality == '720p':
                output_args.update({
                    'vf': 'scale=-2:720',
                    'crf': '23',
                    'b:a': '128k'
                })
            elif quality == '1080p':
                output_args.update({
                    'vf': 'scale=-2:1080',
                    'crf': '21',
                    'b:a': '192k'
                })
            else:  # original
                output_args.update({
                    'crf': '18',
                    'b:a': '320k'
                })

            # Handle subtitle tracks
            subtitle_tracks = [stream for stream in probe['streams'] if stream['codec_type'] == 'subtitle']
            if subtitle_tracks:
                output_args['map'] = '0'  # Map all streams from input
                output_args['c:s'] = 'mov_text'  # Convert subtitles to mov_text format for MP4 compatibility

            # Force pixel format to 8-bit
            output_args['pix_fmt'] = 'yuv420p'

            # Construct the ffmpeg command
            input_stream = ffmpeg.input(input_file)
            output_stream = ffmpeg.output(input_stream, output_file, **output_args)

            # Run the ffmpeg command
            ffmpeg.run(output_stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            # Clean up the temporary subtitle file
            if subtitle_index is not None and os.path.exists(subtitle_file):
                os.remove(subtitle_file)

            return True

    @staticmethod
    def ask_keep_original(file_path, keep_all=None, remove_all=None):
        if keep_all is not None:
            return keep_all
        if remove_all is not None:
            return not remove_all
        
        while True:
            response = input(f"Do you want to keep the original file {file_path}? (y/n/ya/na): ").lower()
            if response == 'y':
                return True
            elif response == 'n':
                return False
            elif response == 'ya':
                return 'keep_all'
            elif response == 'na':
                return 'remove_all'
            else:
                print("Invalid input. Please enter 'y' for yes, 'n' for no, 'ya' for yes to all, or 'na' for no to all.")

    async def upload_file_fast(self, file_path, progress_callback):
        with open(file_path, 'rb') as file:
            return await upload_file(self.client, file, progress_callback=progress_callback)

    def get_video_metadata(self, file_path):
        """
        Safely extract video metadata using ffprobe/ffmpeg.
        Returns tuple of (width, height, duration) or (None, None, None) if extraction fails.
        """
        try:
            probe = ffmpeg.probe(file_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                width = int(video_stream.get('width', 0))
                height = int(video_stream.get('height', 0))
                
                # Try different duration fields
                duration = 0
                if 'duration' in video_stream:
                    duration = int(float(video_stream['duration']))
                elif 'tags' in video_stream and 'DURATION' in video_stream['tags']:
                    duration_str = video_stream['tags']['DURATION']
                    # Parse duration in format HH:MM:SS.ms
                    try:
                        h, m, s = duration_str.split(':')
                        duration = int(float(h) * 3600 + float(m) * 60 + float(s))
                    except:
                        duration = 0
                elif 'duration' in probe['format']:
                    duration = int(float(probe['format']['duration']))
                
                # Fallback for duration
                if duration == 0:
                    # Use ffmpeg to analyze the video duration
                    cmd = ['ffmpeg', '-i', file_path, '-f', 'null', '-']
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    duration_match = re.search(r'time=(\d+):(\d+):(\d+)', result.stderr)
                    if duration_match:
                        h, m, s = map(int, duration_match.groups())
                        duration = h * 3600 + m * 60 + s
                
                return width, height, duration
            
            return None, None, None
            
        except Exception as e:
            return None, None, None

    async def upload_file_with_progress(self, file_path, current_file=0, total_files=0):
        try:
            file_size = os.path.getsize(file_path)
            
            if file_size > SIZE_LIMIT_4GB:
                print(f"Skipping {file_path}: File size exceeds 4GB limit")
                return None
            elif file_size > SIZE_LIMIT_2GB:
                print(f"Warning: {file_path} exceeds 2GB limit. Uploading may fail for non-Premium users.")

            progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, 
                              desc=f'Uploading {os.path.basename(file_path)} [{current_file}/{total_files}]')

            def progress_callback(current, total):
                progress_bar.update(current - progress_bar.n)

            file = await self.upload_file_fast(file_path, progress_callback)
            attributes, mime_type = utils.get_attributes(file_path)
            
            # Check if file is video
            is_video = mime_type.startswith('video/')
            
            if is_video:
                width, height, duration = self.get_video_metadata(file_path)
                
                if width and height and duration:
                    video_attribute = DocumentAttributeVideo(
                        w=width,
                        h=height,
                        duration=duration,
                        supports_streaming=True
                    )
                    
                    attributes = [attr for attr in attributes if not isinstance(attr, DocumentAttributeVideo)]
                    attributes.append(video_attribute)
                else:
                    # Create a minimal video attribute
                    video_attribute = DocumentAttributeVideo(
                        w=1280,  # Default width
                        h=720,   # Default height
                        duration=0,  # Zero duration
                        supports_streaming=True
                    )
                    attributes.append(video_attribute)

            filename_attribute = DocumentAttributeFilename(os.path.basename(file_path))
            attributes = [attr for attr in attributes if not isinstance(attr, DocumentAttributeFilename)]
            attributes.append(filename_attribute)

            media = InputMediaUploadedDocument(
                file=file,
                mime_type=mime_type,
                attributes=attributes,
                thumb=await self.client.upload_file(self.create_thumbnail(file_path, 'thumb.jpg')) if is_video else None,
                force_file=False
            )

            message = await self.client.send_file(
                CHAT_ID,
                media,
                caption=self.remove_extension(os.path.basename(file_path)),
                supports_streaming=is_video
            )

            progress_bar.close()
            print(f'Successfully uploaded: {file_path}')
            return message
        except Exception as e:
            progress_bar.close()
            print(f'Failed to upload {file_path}: {str(e)}')
            return None

    async def send_message(self, message, bold=False):
        try:
            if bold:
                message = f"**{message}**"
            await self.client.send_message(CHAT_ID, message, parse_mode='Markdown')
        except Exception as e:
            print(f'Failed to send message: {e}')

    async def process_directory(self, dir_path, relative_path, total_files, current_file=0):
        if relative_path:
            await self.send_message(relative_path, bold=False)

        items = os.listdir(dir_path)
        files = [f for f in items if os.path.isfile(os.path.join(dir_path, f))]
        dirs = [d for d in items if os.path.isdir(os.path.join(dir_path, d))]
        
        files.sort(key=self.natural_sort_key)
        dirs.sort(key=self.natural_sort_key)

        for file in files:
            if file != 'thumb.jpg':
                file_path = os.path.join(dir_path, file)
                if file_path not in self.uploaded_files:
                    print(f'Processing: {file_path}')
                    
                    current_file += 1
                    message = await self.upload_file_with_progress(file_path, current_file, total_files)

                    if message:
                        self.uploaded_files.add(file_path)
                else:
                    print(f'Skipping already uploaded file: {file_path}')
                    current_file += 1

        for dir_name in dirs:
            subdir_path = os.path.join(dir_path, dir_name)
            subdir_relative_path = os.path.join(relative_path, dir_name) if relative_path else dir_name
            current_file = await self.process_directory(subdir_path, subdir_relative_path, total_files, current_file)

        return current_file

    @staticmethod
    def count_files(directory):
        return sum(len(files) for _, _, files in os.walk(directory))

    async def upload_files(self, file_folder):
        if not await self.client.is_user_authorized():
            print("First time authentication required.")
            phone = input("Please enter your phone number (with country code): ")
            await self.client.start(phone=phone)
            print("New session created. You may need to enter the code you received.")
            if not await self.client.is_user_authorized():
                print("Authentication failed. Please run the script again.")
                return

        try:
            await self.client.get_entity(CHAT_ID)
        except Exception as e:
            print(f"Failed to resolve the chat ID: {e}")
            return

        non_streamable_videos, files_exceeding_2gb, files_exceeding_4gb = self.check_file_issues(file_folder)

        if non_streamable_videos or files_exceeding_2gb or files_exceeding_4gb:
            print("Warning: The following issues were found:")
            
            if non_streamable_videos:
                print("\nNon-MP4 video files (won't support streaming):")
                for video in non_streamable_videos:
                    print(f"- {video}")
                
                convert = input("\nDo you want to convert these videos to MP4 format? (y/n): ").lower()
                if convert == 'y':
                    quality = self.choose_quality()
                    print("\nConverting non-MP4 videos to MP4 format...")
                    keep_all = None
                    remove_all = None
                    
                    # First ask for the deletion preference
                    response = self.ask_keep_original(non_streamable_videos[0])
                    if response == 'keep_all':
                        keep_all = True
                    elif response == 'remove_all':
                        remove_all = True
                    elif not response:  # Single 'no' response
                        remove_all = True
                    
                    # Then process all files
                    for video in non_streamable_videos:
                        output_file = f"{os.path.splitext(video)[0]}.mp4"
                        print(f"Converting: {video} -> {output_file}")
                        
                        subtitle_index = self.choose_subtitle(video)
                        
                        if self.convert_to_mp4(video, output_file, quality, subtitle_index):
                            print(f"Converted: {video} -> {output_file}")
                            # Delete original file if remove_all is True
                            if remove_all:
                                try:
                                    os.remove(video)
                                    print(f"Deleted original file: {video}")
                                except Exception as e:
                                    print(f"Error deleting {video}: {e}")
                        else:
                            print(f"Failed to convert: {video}")
                    
                    # Recheck for file issues after conversion
                    non_streamable_videos, files_exceeding_2gb, files_exceeding_4gb = self.check_file_issues(file_folder)
            
            if files_exceeding_2gb:
                print("\nFiles exceeding 2GB (may fail for non-Premium users):")
                for file in files_exceeding_2gb:
                    print(f"- {file}")
            
            if files_exceeding_4gb:
                print("\nFiles exceeding 4GB (will be skipped):")
                for file in files_exceeding_4gb:
                    print(f"- {file}")
            
            proceed = input("\nDo you want to proceed with the upload? (y/n): ").lower()
            if proceed != 'y':
                print("Upload cancelled.")
                return

        await self.send_message(os.path.basename(file_folder), bold=True)

        total_files = self.count_files(file_folder)
        print(f"Total files to upload: {total_files}")
        
        await self.process_directory(file_folder, "", total_files)

def signal_handler(sig, frame):
    print('Stopping the process gracefully...')
    asyncio.get_event_loop().run_until_complete(uploader.client.disconnect())
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload files to Telegram or list available chats.")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List chats command
    list_parser = subparsers.add_parser('list-chats', help='List all available chats and their IDs')
    
    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload files to a specific chat')
    upload_parser.add_argument("folder", help="Path to the folder containing files to upload")
    upload_parser.add_argument("--chat-id", type=int, help="The Telegram chat ID to upload the files to")

    args = parser.parse_args()

    uploader = TelegramUploader()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    with uploader.client:
        if args.command == 'list-chats':
            uploader.client.loop.run_until_complete(uploader.list_chats())
        elif args.command == 'upload':
            if not os.path.isdir(args.folder):
                print(f"Error: {args.folder} is not a valid directory")
                sys.exit(1)
            CHAT_ID = args.chat_id
            uploader.client.loop.run_until_complete(uploader.upload_files(args.folder))
        else:
            parser.print_help()
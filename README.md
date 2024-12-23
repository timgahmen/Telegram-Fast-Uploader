# Telegram Fast Uploader

A high-performance tool for uploading files to Telegram with support for video streaming, folder structure preservation, and automatic format conversion.

## Features

- Fast recursive file uploads using Telethon and FastTelethon
- Video streaming support with automatic MP4 conversion
- Video quality selection (720p, 1080p, original)
- Automatic thumbnail generation
- Progress tracking with detailed status bars
- Duplicate upload prevention
- GPU acceleration support for video conversion (NVIDIA)
- Subtitle handling and burning capabilities
- Maintains folder hierarchy in Telegram messages
- File size limit checks (2GB/4GB)
- Comprehensive error handling

> Some bugs still exists so use at your own risk

## Requirements

- Python 3.6+
- ffmpeg (`winget install ffmpeg`)
- Required Python packages:
  - telethon
  - FastTelethon (file in this git)
  - ffmpeg-python
  - tqdm
  - cryptg

## Setup

1. Clone the repository:

```bash
git clone https://github.com/ronen1n/Telegram-Fast-Uploader.git
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Get Telegram API credentials:
   - Visit [https://my.telegram.org](https://my.telegram.org)
   - Login and go to "API development tools"
   - Create a new application
   - Copy `api_id` and `api_hash`
   - Update these values in the script

## Usage

List available chats:

```bash
python Telegram_Fast_Uploader.py list-chats
```

Upload files:

```bash
python Telegram_Fast_Uploader.py upload <folder_path> --chat-id <chat_id>
```

Example:

```bash
python Telegram_Fast_Uploader.py upload "C:\Videos" --chat-id "-1002392769999"
```

## License

MIT License - See [LICENSE](LICENSE) file for details.

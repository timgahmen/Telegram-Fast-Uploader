# Telegram Fast Uploader

This script will upload videos with streaming capabilities and other folders and files recursively by order very fast using Telethon and FastTelethon.

## Features

- Uploads files and folders recursively
- Maintains folder structure in Telegram messages
- Upload the videos with streaming capabilities
- Supports video thumbnail generation to unify the videos size showing in telegram (using ffmpeg)
- Displays progress bar for uploads (using tqdm)
- Avoids duplicate uploads

## Requirements

- Python 3.6+
- Telethon
- FastTelethon
- ffmpeg-python
- tqdm

## Setup

1. Clone this repository `git clone https://github.com/ronen1n/Telegram-Fast-Uploader.git`
2. Install the required packages: `pip install -r requirements.txt`
3. Obtain your Telegram API credentials (api_id and api_hash) from https://my.telegram.org (login > API development tools)
4. Update the `api_id`, `api_hash`, and `chat_id` (dont delete the -100) variables in the script
5. Run the script: `python telegram_uploader.py "folder_path"`

## Usage

```
python Telegram_Fast_Uploader.py /path/to/folder
# or
python Telegram_Fast_Uploader.py "C:\folder"
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

"""YouTube Data API integration (OAuth + resumable upload)."""

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def build_credentials(token_data: dict, client_id: str, client_secret: str):
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES,
    )


def upload_video(
    token_data: dict,
    client_id: str,
    client_secret: str,
    video_path: str,
    package: dict,
    privacy: str = "private",
    thumbnail_path: str | None = None,
) -> dict:
    """Upload a video (and its thumbnail) to YouTube. Returns {video_id, url}."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = build_credentials(token_data, client_id, client_secret)
    youtube = build("youtube", "v3", credentials=credentials)

    body = {
        "snippet": {
            "title": package.get("video_title", "")[:100],
            "description": package.get("description", "")[:4900],
            "tags": package.get("tags", [])[:25],
            "defaultLanguage": package.get("language", "es"),
            "defaultAudioLanguage": package.get("language", "es"),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _status, response = request.next_chunk()
    video_id = response["id"]

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumbnail_path)
            ).execute()
        except Exception:
            # Thumbnail failures must not lose the uploaded video.
            pass

    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}

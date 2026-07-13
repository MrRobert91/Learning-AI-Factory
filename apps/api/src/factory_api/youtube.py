"""YouTube Data API integration (OAuth + resumable upload)."""

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


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


def fetch_videos_data(
    token_data: dict, client_id: str, client_secret: str, video_ids: list[str]
) -> list[dict]:
    """Collect stats, analytics and comments per video (each part best-effort)."""
    from googleapiclient.discovery import build

    credentials = build_credentials(token_data, client_id, client_secret)
    youtube = build("youtube", "v3", credentials=credentials)

    results: list[dict] = []
    stats_by_id: dict[str, dict] = {}
    titles_by_id: dict[str, str] = {}
    try:
        listing = (
            youtube.videos()
            .list(part="snippet,statistics", id=",".join(video_ids[:50]))
            .execute()
        )
        for item in listing.get("items", []):
            titles_by_id[item["id"]] = item["snippet"]["title"]
            stats_by_id[item["id"]] = item.get("statistics", {})
    except Exception:
        pass

    analytics_by_id: dict[str, dict] = {}
    try:
        yt_analytics = build("youtubeAnalytics", "v2", credentials=credentials)
        report = (
            yt_analytics.reports()
            .query(
                ids="channel==MINE",
                startDate="2000-01-01",
                endDate="2100-01-01",
                metrics=(
                    "views,estimatedMinutesWatched,averageViewDuration,"
                    "averageViewPercentage"
                ),
                dimensions="video",
                filters=f"video=={','.join(video_ids[:50])}",
            )
            .execute()
        )
        headers = [c["name"] for c in report.get("columnHeaders", [])]
        for row in report.get("rows", []) or []:
            entry = dict(zip(headers, row, strict=False))
            analytics_by_id[str(entry.pop("video", ""))] = entry
    except Exception:
        pass

    for video_id in video_ids:
        comments: list[str] = []
        try:
            threads = (
                youtube.commentThreads()
                .list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=50,
                    order="relevance",
                    textFormat="plainText",
                )
                .execute()
            )
            for item in threads.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(snippet.get("textDisplay", ""))
        except Exception:
            pass
        results.append(
            {
                "video_id": video_id,
                "title": titles_by_id.get(video_id, video_id),
                "stats": stats_by_id.get(video_id, {}),
                "analytics": analytics_by_id.get(video_id, {}),
                "comments": comments,
            }
        )
    return results


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

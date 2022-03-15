import psycopg2.extras
from config import *
from sql_helper import *
from datetime import datetime
import googleapiclient.discovery
import googleapiclient.errors

scopes = ["https://www.googleapis.com/auth/youtube.readonly"]

youtube_base_url = "https://www.youtube.com/watch?v=%s"
youtube_api_key = "AIzaSyDK-HwpEZa2oIQAuU1cI__e7nWOVJ4SX_4"
api_service_name = "youtube"
api_version = "v3"
youtube = googleapiclient.discovery.build(api_service_name, api_version, developerKey=youtube_api_key)

keepalive_kwargs = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 5,
    "keepalives_count": 5,
}

postgres = psycopg2.connect(**postgres_con, **keepalive_kwargs)
exists_series_ids = []
exists_video_ids = []


def extract_lessons_for_channel_id(source_id: int, channel_id: str, category: str, label: str):
    global exists_series_ids, exists_video_ids
    exists_series_ids.clear()
    exists_video_ids.clear()
    insert_source(source_id, category)
    cursor = postgres.cursor()
    cursor.execute('select id from lessons where "sourceId" = %s;', (source_id,))
    exists_video_ids = [row[0] for row in cursor.fetchall()]
    cursor.execute('select id from series where "sourceId" = %s', (source_id,))
    exists_series_ids = [row[0] for row in cursor.fetchall()]
    cursor.execute('select id from categories where "sourceId" = %s', (source_id,))
    exists_categories_ids = [row[0] for row in cursor.fetchall()]
    original_category_id = int(str(get_hash_for_string(category))[:8])
    category_id = get_hash_for_id(source_id, original_category_id)
    if category_id not in exists_categories_ids:
        cursor.execute(
            '''INSERT INTO categories(id,"originalId","sourceId",category) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
            , (category_id, original_category_id, source_id, category,))
        exists_categories_ids.append(original_category_id)
        postgres.commit()
    cursor.close()
    # get_channel_videos(channel_id, "", source_id, category)
    get_channel_videos_from_uploads(channel_id, source_id, category)
    insert_labels(label, source_id, category_id)


def insert_labels(label: str, source_id: int, category_id: int):
    clear_labels(postgres, source_id)
    cursor = postgres.cursor()
    cursor.execute('''SELECT id from lessons where "sourceId" = %s AND "categoryId" = %s ORDER BY timestamp DESC LIMIT 10;''',
                   (source_id, category_id, ))
    labels_ids = [row[0] for row in cursor.fetchall()]
    for lesson_id in labels_ids:
        cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                       (label, source_id, lesson_id))
    cursor.close()
    postgres.commit()


def insert_source(source_id: int, source_name: str):
    cursor = postgres.cursor()
    cursor.execute('''INSERT INTO sources(id,label) VALUES(%s,%s) ON CONFLICT (id) DO NOTHING;''',
                   (source_id, source_name,))
    cursor.close()
    postgres.commit()


def get_channel_videos(channel_id: str, next_token: str, source_id: int, category: str):
    print("get_channel_videos", category)
    cursor = postgres.cursor()
    request = youtube.playlists().list(
        maxResults=50,
        pageToken=next_token,
        part="contentDetails,snippet",
        channelId=channel_id
    )
    response = request.execute()
    for item in response["items"]:
        playlist_id = item['id']
        original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
        series_id = get_hash_for_id(source_id, original_playlist_id)
        title = item['snippet']['title']
        if series_id not in exists_series_ids:
            cursor.execute(
                '''INSERT INTO series(id,"originalId","sourceId",serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                , (series_id, original_playlist_id, source_id, title[:80],))
            exists_series_ids.append(series_id)
            postgres.commit()
        print("get_playlist_videos", title)
        get_playlist_videos(playlist_id, "", source_id, category)
    cursor.close()
    has_more = 'nextPageToken' in response
    if has_more:
        get_channel_videos(channel_id, response["nextPageToken"], source_id, category)


def get_channel_videos_from_uploads(channel_id: str, source_id: int, category: str):
    print("get_channel_videos", category)
    request = youtube.channels().list(
        part="contentDetails",
        id=channel_id
    )
    response = request.execute()
    for item in response["items"]:
        uploads_id = item['contentDetails']['relatedPlaylists']['uploads']
        original_playlist_id = int(str(get_hash_for_string(uploads_id))[:8])
        series_id = get_hash_for_id(source_id, original_playlist_id)
        title = "כללי"
        if series_id not in exists_series_ids:
            cursor = postgres.cursor()
            cursor.execute(
                '''INSERT INTO series(id,"originalId","sourceId",serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                , (series_id, original_playlist_id, source_id, title[:80],))
            exists_series_ids.append(series_id)
            postgres.commit()
            cursor.close()
        get_playlist_videos(uploads_id, "", source_id, category)


def get_playlist_videos(playlist_id: str, next_token: str, source_id: int, category: str):
    request = youtube.playlistItems().list(
        maxResults=50,
        pageToken=next_token,
        part="contentDetails,snippet",
        playlistId=playlist_id
    )
    response = request.execute()
    ids = [item["contentDetails"]["videoId"] for item in response["items"] if
           not should_filter_video(source_id, item["contentDetails"]["videoId"])]
    if len(ids) > 0:
        yt_api_get_videos(ids, source_id, category, playlist_id)
    has_more = 'nextPageToken' in response
    if has_more:
        get_playlist_videos(playlist_id, response["nextPageToken"], source_id, category)


def yt_api_get_videos(ids: list, source_id: int, category: str, playlist_id: str):
    global exists_video_ids
    cursor = postgres.cursor()
    ids_query = ",".join(ids)
    request = youtube.videos().list(
        part="contentDetails,snippet",
        id=ids_query
    )
    response = request.execute()
    original_category_id = int(str(get_hash_for_string(category))[:8])
    category_id = get_hash_for_id(source_id, original_category_id)
    original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
    series_id = get_hash_for_id(source_id, original_playlist_id)
    for item in response["items"]:
        video_id = item["id"]
        original_video_id = int(str(get_hash_for_string(video_id))[:8])
        _id = get_hash_for_id(source_id, original_video_id)
        date = datetime.strptime(item["snippet"]["publishedAt"], '%Y-%m-%dT%H:%M:%Sz')
        body = {
            "id": _id,
            "sourceId": source_id,
            "originalId": original_video_id,
            "title": item["snippet"]['title'],
            "categoryId": category_id,
            "seriesId": series_id,
            "ravId": None,
            "dateStr": get_heb_date(date),
            "duration": get_duration_in_seconds(item["contentDetails"]["duration"]),
            "videoUrl": youtube_base_url % video_id,
            "audioUrl": None,
            "timestamp": date.timestamp(),
        }
        exists_video_ids.append(_id)
        add_lesson_to_db(cursor, body)
        postgres.commit()
    cursor.close()


def should_filter_video(source_id: int, video_id: str) -> bool:
    global exists_video_ids
    original_video_id = int(str(get_hash_for_string(video_id))[:8])
    _id = get_hash_for_id(source_id, original_video_id)
    return _id in exists_video_ids
    # return False


def grab_yotube():
    extract_lessons_for_channel_id(50, "UCeDrtyuUbMLB_z6razI33dQ", "אמונה-הסדר חיפה", "הסדר חיפה - אחרונים")
    extract_lessons_for_channel_id(51, "UCBN2YMjFoJHX1qlpEcra29w", "ישיבת המאירי", "ישיבת המאירי - אחרונים")
    extract_lessons_for_channel_id(52, "UCMSm6HR03oQ7HfgOhtumEhQ", "הסדר טפחות", 'הסדר טפחות - אחרונים')
    extract_lessons_for_channel_id(60, "UCS6OvEopzPGEEwYbAG4ismA", "מעלה אדומים", 'ברכת משה- מעלה אדומים')
    extract_lessons_for_channel_id(61, "UCAcP4Dx-c66fPD5fYcYF0PQ", "ישיבת הכותל", "ישיבת הכותל - אחרונים")
    extract_lessons_for_channel_id(62, "UCjswceInZ37d8RIjHDz5ifw", "ישיבת ר״ג", "ישיבת רמת גן - אחרונים")
    extract_lessons_for_channel_id(63, "UCpEUk0Kpt07ms4zHWFsXxhg", "ישיבת הר עציון", "ישיבת הר עציון - אחרונים")
    extract_lessons_for_channel_id(64, "UCkwxRNj-7Iu1LlHJfKzl2Gw", "ישיבת הר ברכה", "ישיבת הר ברכה - אחרונים")
    extract_lessons_for_channel_id(65, "UC1BIlJW-jVw_EUnj0p-LIgQ", "חב״ד", "הרב שניאור אשכנזי")
    extract_lessons_for_channel_id(66, "UCp_YIYD7Ol3DXp6iR8A0ppg", "הרב אורי שרקי", "הרב אורי שרקי - אחרונים")
    extract_lessons_for_channel_id(67, "UC1UJunP8IpS4xfCRtB2HrPQ", "ישיבת שבי חברון", "ישיבת שבי חברון - אחרונים")
    extract_lessons_for_channel_id(68, "UCLUz-ovexcSqyW1xjShqZ7A", "דף יומי", "סיני - דף יומי")
    extract_lessons_for_channel_id(69, "UCLUz-ovexcSqyW1xjShqZ7A", "הרב ראובן ששון", "הרב ראובן ששון - אחרונים")
    postgres.close()


if __name__ == "__main__":
    pass
    grab_yotube()

urlC = '''
curl \
'https://youtube.googleapis.com/youtube/v3/playlists?part=player%2snippet%2CcontentDetails&channelId=UC3MjXqiy3SNNSWiixX2Mybw&maxResults=25&pageToken=CBkQAA&key=AIzaSyDK-HwpEZa2oIQAuU1cI__e7nWOVJ4SX_4' \
--header 'Accept: application/json' \
--compressed
'''

# UUEAZVyOtukIOH4BJ3gHKdng
# ssh -i ~/.ssh/id_rsa -L 4242:localhost:5432 bitnami@3.70.156.78 -N
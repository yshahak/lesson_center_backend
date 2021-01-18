import traceback
import subprocess
import psycopg2.extras
import youtube_dl
from config import *
from sql_helper import *
from datetime import datetime

youtube_base_url = "https://www.youtube.com/watch?v=%s"
postgres = psycopg2.connect(**postgres_con)


def extract_lessons_for_channel_id(source_id: int, channel_url: str, category: str, label: str):
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
    ydl_opts = {
        'ignoreerrors': True,
        'youtube_include_dash_manifest': False
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        cursor = postgres.cursor()
        videos = ydl.extract_info("{}/playlists?view=1&sort=dd&shelf_id=0".format(channel_url), download=False)
        for playlist in videos['entries']:
            playlist_id = playlist['id']
            original_playlist_id = int(str(get_hash_for_string(playlist_id))[:8])
            series_id = get_hash_for_id(source_id, original_playlist_id)
            if series_id not in exists_series_ids:
                cursor.execute(
                    '''INSERT INTO series(id,"originalId","sourceId",serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                    , (series_id, original_playlist_id, source_id, playlist['title'][:80],))
                exists_series_ids.append(playlist)
                postgres.commit()
            for video in playlist['entries']:
                if not video:
                    continue
                video_id = video['id']
                original_video_id = int(str(get_hash_for_string(video_id))[:8])
                _id = get_hash_for_id(source_id, original_video_id)
                if _id in exists_video_ids:
                    continue
                date = datetime.strptime(video['upload_date'], '%Y%m%d')
                body = {
                    "id": _id,
                    "sourceId": source_id,
                    "originalId": original_video_id,
                    "title": video['title'],
                    "categoryId": category_id,
                    "seriesId": series_id,
                    "ravId": None,
                    "dateStr": get_heb_date(date),
                    "duration": video['duration'],
                    "videoUrl": youtube_base_url % video_id,
                    "audioUrl": None,
                    "timestamp": date.timestamp(),
                }
                exists_video_ids.append(_id)
                print(body)
                add_lesson_to_db(cursor, body)
                postgres.commit()
        cursor.close()
    run_results = subprocess.run(['youtube-dl', '--get-id', channel_url], stdout=subprocess.PIPE)
    channel_videos_ids = run_results.stdout.decode("utf-8").split('\n')
    channel_videos_ids.remove('')
    cursor = postgres.cursor()
    for video_id in channel_videos_ids:
        original_video_id = int(str(get_hash_for_string(video_id))[:8])
        _id = get_hash_for_id(source_id, original_video_id)
        if _id in exists_video_ids:
            continue
        video = ydl.extract_info(youtube_base_url % (video_id,), download=False)
        date = datetime.strptime(video['upload_date'], '%Y%m%d')
        body = {
            "id": _id,
            "sourceId": source_id,
            "originalId": original_video_id,
            "title": video['title'],
            "categoryId": category_id,
            "seriesId": series_id,
            "ravId": None,
            "dateStr": get_heb_date(date),
            "duration": video['duration'],
            "videoUrl": youtube_base_url % video_id,
            "audioUrl": None,
            "timestamp": date.timestamp(),
        }
        exists_video_ids.append(_id)
        print(body)
        add_lesson_to_db(cursor, body)
        postgres.commit()
    cursor.close()
    insert_labels(label, source_id)


def extract_audio_from_youtube_link(link: str):
    ydl_opts = {
        'format': 'bestaudio',
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=False)['formats'][0]
        if 'fragment_base_url' in info:
            url = info['fragment_base_url']
        else:
            url = info['url']
        print(url)


def insert_labels(label: str, source_id: int):
    clear_labels(postgres, source_id)
    cursor = postgres.cursor()
    cursor.execute('''SELECT id from lessons where "sourceId" = %s ORDER BY updatedat DESC LIMIT 10;''',
                   (source_id,))
    labels_ids = [row[0] for row in cursor.fetchall()]
    for lesson_id in labels_ids:
        cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                       (label, source_id, lesson_id))
    cursor.close()
    postgres.commit()


if __name__ == "__main__":
    pass
    # extract_lessons_for_channel_id(50, "https://www.youtube.com/channel/UCeDrtyuUbMLB_z6razI33dQ", "אמונה-הסדר חיפה" , "הסדר חיפה - אחרונים")
    # extract_lessons_for_channel_id(51, "https://www.youtube.com/channel/UCBN2YMjFoJHX1qlpEcra29w", "ישיבת המאירי", "ישיבת המאירי - אחרונים")
    # extract_lessons_for_channel_id(60, "https://www.youtube.com/channel/UCS6OvEopzPGEEwYbAG4ismA", "מעלה אדומים", 'ברכת משה- מעלה אדומים')
    # extract_lessons_for_channel_id(61, "https://www.youtube.com/channel/UCAcP4Dx-c66fPD5fYcYF0PQ", "ישיבת הכותל", "ישיבת הכותל - אחרונים")
    extract_lessons_for_channel_id(62, "https://www.youtube.com/user/YeshivatRamatGan", "ישיבת ר״ג", "ישיבת רמת גן - אחרונים")
    postgres.close()

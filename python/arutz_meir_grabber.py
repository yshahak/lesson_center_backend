# coding=utf-8
from __future__ import unicode_literals
import requests
import time
from pyluach.dates import HebrewDate
import traceback
import datetime
import psycopg2.extras
from config import *
from sql_helper import *

postgres = psycopg2.connect(**postgres_con)

now = get_timestamp()
counter = 0
source_id = 2
meir_base_url = 'http://www.meirtv.co.il/site/content_idx.asp?idx=%s'
base_url = 'http://82.80.198.104/MidrashServices/api/'
categories_url = '%sCategories' % base_url
sets_url = '%sSets' % base_url
ravs_url = '%sRabbis' % base_url
search_for_category_url = '%sLessons?catId=%s&page=%s'
search_for_sets_url = '%sLessons?setId=%s'
vimeo_url = 'https://api.vimeo.com/videos/%s'
vimeo_API1 = 'd482105551a9c3fb8673259fe5277a81'
vimeo_API2 = '3522b8c3a30812bbab8572551f0fea10'
source = 'arutz_meir'

sets_arr = set()
exists_original_ids = []
categories_ids = []
with_no_series = set()


def grab():
    global sets_arr, exists_original_ids, categories_ids
    fill_complementary_tables()
    print('getting ids')
    cursor = postgres.cursor()
    cursor.execute('select originalid from lessons where sourceid = %s;', (source_id,))
    exists_original_ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    print('got ids')
    for category in categories_ids:
        try:
            grab_for_category(category)
        except Exception:
            print('exception for', category)
            traceback.print_exc()


def fill_complementary_tables():
    global sets_arr, exists_original_ids, categories_ids
    cursor = postgres.cursor()
    response = requests.get(categories_url)
    categories = response.json()
    for entry in categories:
        orginalid = entry['Id']
        categories_ids.append(orginalid)
        cursor.execute(
            '''INSERT INTO categories(id,originalid,sourceid,category) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
            , (get_hash_for_id(source_id, orginalid), orginalid, source_id, entry['Title'],))
    postgres.commit()
    response = requests.get(sets_url)
    sets = response.json()
    for entry in sets:
        orginalid = entry['Id']
        sets_arr.add(orginalid)
        cursor.execute(
            '''INSERT INTO series(id,originalid,sourceid,serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
            , (get_hash_for_id(source_id, orginalid), orginalid, source_id, entry['Title'],))
    add_missing_serie_id(cursor, 0, 'ללא')
    add_missing_serie_id(cursor, 21022, 'אורות התורה - הרב ערן טמיר')
    add_missing_serie_id(cursor, 21193, 'בניין אמונה - הרב ערן טמיר -התשע')
    add_missing_serie_id(cursor, 21393, 'חפץ חיים - הרב דב ביגון')
    add_missing_serie_id(cursor, 21691, 'מוסר אביך - הרב יואב מלכא')
    add_missing_serie_id(cursor, 22264, 'ספר אורות - הרב דב ביגון')
    add_missing_serie_id(cursor, 22658, 'יום עיון בנושא אמת - התשעה')
    add_missing_serie_id(cursor, 22660, 'שמירת הלשון - התשעה')
    add_missing_serie_id(cursor, 22723, 'ספרי חוזרים בתשובה')
    add_missing_serie_id(cursor, 22877, 'עשה לך רב - תשעז')
    add_missing_serie_id(cursor, 22882, 'עשרת הדברות לזוגיות')
    add_missing_serie_id(cursor, 22888, 'יום עיון בענייני ירושלים - תשעז')
    add_missing_serie_id(cursor, 22899, 'יום עיון לזכרו של מרן הרב קוק - תשעז')
    add_missing_serie_id(cursor, 22942, 'נתיבות עולם למהר"ל מפראג - התשעח')
    add_missing_serie_id(cursor, 22943, 'יום עיון לקראת יום העצמאות - התשעח')
    add_missing_serie_id(cursor, 22952, 'הלכות מזוזה - התשעח')
    add_missing_serie_id(cursor, 22955, 'הלכות דרך ארץ ומוסר בסעודה - התשעח')
    add_missing_serie_id(cursor, 22960, 'הלכות צניעות וקדושת עם ישראל - התשעח')
    add_missing_serie_id(cursor, 22965, 'נפש החיים  -הרב דב ביגון - התשעח')
    add_missing_serie_id(cursor, 22972, 'נבואות לדורות ספר מלכים - התשעח')
    add_missing_serie_id(cursor, 22981, 'עין אי"ה - תשעט')
    add_missing_serie_id(cursor, 22982, 'להקשיב לפרשה - תשעט')
    add_missing_serie_id(cursor, 22985, 'אגדות חז"ל - הרב יואב מלכא')
    add_missing_serie_id(cursor, 22986, 'יום עיון בנושא חג הסיגד - תשעט')
    add_missing_serie_id(cursor, 22989, 'דף יומי מסכת חולין - תשעט')
    add_missing_serie_id(cursor, 22990, "ספר 'לנבוכי הדור' למרן הרב קוק - תשעט")
    add_missing_serie_id(cursor, 22991, 'ספר מוסר אביך למרן הרב קוק')
    add_missing_serie_id(cursor, 22993, 'משבירה לתיקון התמודדות עם משבר')
    add_missing_serie_id(cursor, 22995, 'לימוד ספר תהילים - תשעט')
    add_missing_serie_id(cursor, 22996, 'מדרש תנחומא - תשעט')
    add_missing_serie_id(cursor, 22998, 'לימוד תורה פגישה עם עצמינו')
    add_missing_serie_id(cursor, 23003, 'כתר שם טוב - תשעט')
    add_missing_serie_id(cursor, 23011, 'ספר הכוזרי אלול תשעט')
    add_missing_serie_id(cursor, 23014, 'שיעורים באורות הקודש')
    add_missing_serie_id(cursor, 23015, 'הרב קוק על פרשת השבוע - תשפ')

    response = requests.get(ravs_url)
    ravs = response.json()
    for entry in ravs:
        orginalid = entry['Id']
        cursor.execute(
            '''INSERT INTO ravs(id,originalid,sourceid,rav) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
            , (get_hash_for_id(source_id, orginalid), orginalid, source_id, entry['FullName'],))
    cursor.close()
    postgres.commit()
    grab_widgets()


def add_missing_serie_id(cursor, serie_id, name):
    global sets_arr
    cursor.execute(
        '''INSERT INTO series(id,originalid,sourceid,serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO 
        UPDATE SET serie = %s;'''
        , (get_hash_for_id(source_id, serie_id), serie_id, source_id, name, name))
    sets_arr.add(serie_id)


def grab_widgets():
    clear_labels(postgres, source_id)
    grab_widget(4)
    grab_widget(5)
    postgres.commit()


def grab_widget(widget: int):
    response = requests.get('%swidgets?pageBox=%s' % (base_url, widget,), timeout=15)
    lessons = response.json()
    for entry in lessons:
        if 'Lessons' in entry and entry['Lessons']:
            iterate_over_lessons(entry['Lessons'])
            cursor = postgres.cursor()
            label = entry['Title']
            print('grabbing ', label)
            for lesson in entry['Lessons']:
                cursor.execute('''INSERT INTO labels (label,sourceid,lessonid) VALUES(%s,%s,%s);''',
                               (label, source_id, get_hash_for_id(source_id, lesson['Id'])))
            cursor.close()


def grab_for_category(category_id: int, page=1):
    response = requests.get(search_for_category_url % (base_url, category_id, page), timeout=15)
    lessons = response.json()
    cursor = postgres.cursor()
    if lessons:
        iterate_over_lessons(lessons)
        grab_for_category(category_id, page + 1)
    cursor.close()


def iterate_over_lessons(lessons: dict):
    cursor = postgres.cursor()
    for lesson in lessons:
        if lesson:
            try:
                body = grab_lesson(lesson)
                if body:
                    add_lesson_to_db(cursor, now, body)
                    postgres.commit()
                    break
            except Exception as e:
                print("Error !!! in lesson={0}\ne={1}".format(lesson, traceback.format_exc()))
    cursor.close()


def grab_lesson(lesson):
    global exists_original_ids
    original_id = lesson["Id"]
    if original_id in exists_original_ids:
        print('id exists', original_id)
        return None
    date_str = lesson["RecordDate"]
    format = '%Y-%m-%d %H:%M:%S.%f' if '.' in date_str else '%Y-%m-%d %H:%M:%S'
    date_time_obj = datetime.datetime.strptime(date_str.replace('T', ' '), format)
    timestamp = datetime.datetime.timestamp(date_time_obj)
    id = get_hash_for_id(source_id, original_id)
    original_series_id = lesson["SetId"]
    if original_series_id in sets_arr:
        pass
    else:
        with_no_series.add(original_series_id)
        print("!missing set")
        print(with_no_series)
        sets_arr.add(original_series_id)
    video_url = get_video_url(lesson['VimeoId'])
    body = {
        "id": id,
        "sourceid": source_id,
        "originalid": original_id,
        "title": lesson["Title"],
        "categoryid": get_hash_for_id(source_id, lesson["CategoryId"]),
        "seriesId": get_hash_for_id(source_id, original_series_id),
        "ravId": get_hash_for_id(source_id, lesson["RabbiId"]),
        "dateStr": get_heb_date(date_time_obj),
        "duration": lesson["LessonLength"],
        "videoUrl": video_url,
        "audioUrl": lesson["Mp3Path"],
        "timestamp": timestamp,
    }
    exists_original_ids.append(original_id)
    return body


flag_api = False


def get_video_url(vimeo_id: int, first=True):
    global flag_api
    if not vimeo_id:
        return None
    time.sleep(0.1)
    try:
        api = vimeo_API1 if flag_api else vimeo_API2
        response = requests.get(vimeo_url % vimeo_id, headers={'Authorization': 'bearer %s' % api}, timeout=15)
        vimeo = response.json()
        if 'files' not in vimeo:
            raise Exception('missing files')
        return vimeo['files'][0]['link']
    except:
        print(first, ' couldn"t grab %s' % vimeo_url % vimeo_id, "bearer %s" % api, )
        flag_api = not flag_api
        # traceback.print_exc()
        return get_video_url(vimeo_id, False) if first else None


def get_heb_date(date_time_obj):
    heb = HebrewDate.from_pydate(date_time_obj)
    month = (month_dict[heb.month])
    remains = heb.year - 5700
    dosens = 10 * int(remains / 10)
    last = remains % 10
    year = u'התש%s%s' % (gimatria_map[dosens], gimatria_map[last])
    heb_date = '%s %s %s' % (day_list[heb.day], month, year)
    return heb_date


if __name__ == '__main__':
    grab()
    # http://player.vimeo.com/external/335685696.hd.mp4?s=3fe2de2efc420884a4f6c13d0986e0cb2255a062&profile_id=175&oauth2_token_id=1009673393
    # exeption in category exception for 4095 exception for 4575,4576,4713,4747,4960,3966,

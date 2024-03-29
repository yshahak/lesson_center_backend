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
from youtube_grabber import extract_lessons_for_channel_id

postgres = psycopg2.connect(**postgres_con)

now = get_timestamp()
counter = 0
source_id = 2
meir_base_url = 'http://www.meirtv.co.il/site/content_idx.asp?idx=%s'
base_url = 'https://meirtv.com/wp-json/v1/'
categories_url = '%sCategories' % base_url
sets_url = '%sSets' % base_url
ravs_url = '%sRabbis' % base_url
search_for_category_url = '%sLessons?catId=%s&page=%s'
search_for_rav_url = '%sLessons?rabbiId=%s&page=%s'
search_for_sets_url = '%sLessons?setId=%s'
vimeo_url = 'https://api.vimeo.com/videos/%s'
vimeo_API1 = '931a8c1a665f1110ce0d7205f06529be'
# vimeo_API1 = 'd482105551a9c3fb8673259fe5277a81'
vimeo_API2 = '3522b8c3a30812bbab8572551f0fea10'
source = 'arutz_meir'

ravs_arr = set()
sets_arr = set()
categories_ids = set()
with_no_series = set()

print('getting ids')

cursor = postgres.cursor()
cursor.execute('select "originalId" from lessons where "sourceId" = %s;', (source_id,))
exists_original_ids = [row[0] for row in cursor.fetchall()]
cursor.execute('select "originalId" from series where "sourceId" = %s;', (source_id,))
sets_arr.update([row[0] for row in cursor.fetchall()])
cursor.execute('select "originalId" from categories where "sourceId" = %s;', (source_id,))
categories_ids.update([row[0] for row in cursor.fetchall()])
cursor.execute('select "originalId" from ravs where "sourceId" = %s;', (source_id,))
ravs_arr.update([row[0] for row in cursor.fetchall()])
cursor.close()
print('got ids')


def grab():
    global categories_ids, ravs_arr
    fill_complementary_tables()
    # for category in categories_ids:
    #     try:
    #         grab_for_category(category)
    #     except Exception:
    #         print('exception for', category)
    #         traceback.print_exc()
    for rav in ravs_arr:
        try:
            grab_for_rav(rav)
        except Exception:
            print('exception for', rav)
            traceback.print_exc()


def fill_complementary_tables():
    global sets_arr, exists_original_ids, categories_ids, ravs_arr
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
        if orginalid in sets_arr:
            continue
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
    add_missing_serie_id(cursor, 21639, 'לימוד בוקר בפרשה')
    add_missing_serie_id(cursor, 22561, 'ספר ישעיהו')
    add_missing_serie_id(cursor, 21025, 'אורות התשובה')
    add_missing_serie_id(cursor, 23018, 'פרשת השבוע - מחזור תש״פ')
    add_missing_serie_id(cursor, 23019, 'הגדה של פסח - מחזור תש״פ')
    add_missing_serie_id(cursor, 23020, 'שורשיה העמוקים של ארץ ישראל')
    add_missing_serie_id(cursor, 23022, 'פרשת השבוע - מחזור תש״פ')
    add_missing_serie_id(cursor, 23025, 'יום עיון במשנת הרב קוק - מחזור תש״פ')
    add_missing_serie_id(cursor, 23026, 'ארבעה נכנסו לפרדס - מחזור תש״פ')
    add_missing_serie_id(cursor, 23027, 'טעמי המצות - מחזור תש״פ')
    add_missing_serie_id(cursor, 23028, 'זיו הפרשה והמועדים - מחזור תש״פ')
    add_missing_serie_id(cursor, 23030, 'סוגיות תשובה בתנ"ך')
    add_missing_serie_id(cursor, 23004, 'לומדים לקרוא תנ"ך ספר ישעיה - מחזור תשע״ט')
    postgres.commit()
    response = requests.get(ravs_url)
    ravs = response.json()
    for entry in ravs:
        orginalid = entry['Id']
        ravs_arr.add(orginalid)
        cursor.execute(
            '''INSERT INTO ravs(id,originalid,sourceid,rav) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
            , (get_hash_for_id(source_id, orginalid), orginalid, source_id, entry['FullName'],))
    cursor.close()
    postgres.commit()
    grab_widgets()


def add_missing_serie_id(cursor, serie_id: int, name: str):
    global sets_arr
    if serie_id not in sets_arr:
        cursor.execute(
            '''INSERT INTO series(id,"originalId","sourceId",serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO 
            UPDATE SET serie = %s;'''
            , (get_hash_for_id(source_id, serie_id), serie_id, source_id, name, name))
        sets_arr.add(serie_id)


def add_missing_category_id(cursor, category_id, name):
    global categories_ids
    if category_id not in categories_ids:
        cursor.execute(
            '''INSERT INTO categories(id,"originalId","sourceId",category) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO 
            UPDATE SET category = %s;'''
            , (get_hash_for_id(source_id, category_id), category_id, source_id, name, name))
        categories_ids.add(category_id)


def add_missing_rav_id(cursor, rav_id, name):
    global ravs_arr
    if rav_id not in categories_ids:
        cursor.execute(
            '''INSERT INTO ravs(id,"originalId","sourceId",rav) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO 
            UPDATE SET rav = %s;'''
            , (get_hash_for_id(source_id, rav_id), rav_id, source_id, name, name))
        ravs_arr.add(rav_id)


def grab_widgets():
    print("grabbing arutz meir widgets")
    clear_labels(postgres, source_id)
    try:
        grab_widget(4)
        grab_widget(5)
        postgres.commit()
    except Exception as e:
        print("Error grab widget {}".format(traceback.format_exc()))


def grab_widget(widget: int):
    response = requests.get('%swidgets?pageBox=%s' % (base_url, widget,), timeout=15)
    try:
        lessons = response.json()
        for entry in lessons:
            if 'Lessons' in entry and entry['Lessons']:
                label = "מכון מאיר - {0}".format(entry['Title'])
                iterate_over_lessons(entry['Lessons'], label)
    except Exception as e:
        print("Error grab lesson {} ".format(response, ))
        print("Error grab lesson {} ".format(traceback.format_exc(), ))
        raise e


def grab_page(page: int = 0, is_main_page: bool = False):
    print("grabbing page", page)
    try:
        response = requests.get('%svideo-shiurim?limit=20&offset=%s' % (base_url, page * 20,), timeout=15)
        lessons = response.json()
        if not lessons:
            print("no more lessons!")
            return
        cursor = postgres.cursor()
        pulled = False
        for entry in lessons:
            (pulled, lesson_id) = grab_lesson2(entry, cursor)
            if pulled:
                pulled = True
            if lesson_id and is_main_page and page == 0:
                cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                               ('ערוץ מאיר - אחרונים', source_id, lesson_id))
        cursor.close()
        postgres.commit()
        if pulled:
            grab_page(page + 1)
        else:
            print("didn't grap any item, page=", page)
    except Exception as e:
        print("Error grab lesson {} {} ".format(page, traceback.format_exc(), ))
        raise e


def grab_for_category(category_id: int, page=1):
    response = requests.get(search_for_category_url % (base_url, category_id, page), timeout=15)
    lessons = response.json()
    if lessons:
        iterate_over_lessons(lessons)
        grab_for_category(category_id, page + 1)


def grab_for_rav(rav_id: int, page=1):
    print("request", search_for_rav_url % (base_url, rav_id, page))
    response = requests.get(search_for_rav_url % (base_url, rav_id, page), timeout=15)
    lessons = response.json()
    if lessons:
        iterate_over_lessons(lessons)
        grab_for_rav(rav_id, page + 1)


def iterate_over_lessons(lessons: dict, label=None):
    cursor = postgres.cursor()
    for lesson in lessons:
        if lesson:
            try:
                exist, body = grab_lesson(lesson)
                if exist and label:
                    cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                                   (label, source_id, get_hash_for_id(source_id, lesson['Id'])))
                if body:
                    add_lesson_to_db(cursor, body)
                postgres.commit()
            except Exception as e:
                print("Error !!! in lesson={0}\ne={1}".format(lesson, traceback.format_exc()))
                break
    cursor.close()


def grab_lesson(lesson):
    global exists_original_ids
    original_id = lesson["Id"]
    if original_id in exists_original_ids:
        print('id exists', original_id)
        return True, None
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
        "sourceId": source_id,
        "originalId": original_id,
        "title": lesson["Title"],
        "categoryId": get_hash_for_id(source_id, lesson["CategoryId"]),
        "seriesId": get_hash_for_id(source_id, original_series_id),
        "ravId": get_hash_for_id(source_id, lesson["RabbiId"]),
        "dateStr": get_heb_date(date_time_obj),
        "duration": lesson["LessonLength"],
        "videoUrl": video_url,
        "audioUrl": lesson["Mp3Path"],
        "timestamp": timestamp,
    }
    exists_original_ids.append(original_id)
    return True, body


def grab_lesson2(lesson: dict, cursor) -> (bool, int):
    idx = lesson["idxnumber"][0]
    original_id = int(idx) if idx else lesson["ID"]
    id = get_hash_for_id(source_id, original_id)
    if original_id in exists_original_ids:
        print('id exists', lesson)
        return False, id
    if 'mador' not in lesson:
        print("trouble!", lesson)
    else:
        if lesson['mador'][0]['term_id'] == 13308:  # kids
            print('kids!', lesson)
            return False
        if lesson['mador'][0]['term_id'] == 18532:  # music
            print('music!', lesson)
            return False
    date_str = lesson["post_date"]
    format = '%Y-%m-%d %H:%M:%S.%f' if '.' in date_str else '%Y-%m-%d %H:%M:%S'
    date_time_obj = datetime.datetime.strptime(date_str.replace('T', ' '), format)
    timestamp = datetime.datetime.timestamp(date_time_obj)
    lesson_length = lesson["lessonlength"][0]
    duration = int(lesson_length) if check_int(lesson_length) else 0
    original_series_id = get_original_series_id(lesson)
    video_url = get_video_url(lesson['vimeo_file'][0])
    if not video_url and lesson['youtube_file'][0] != "":
        video_url = "https://www.youtube.com/watch?v=%s" % (lesson['youtube_file'][0])
    audio_url = lesson["mp3_file"][0]
    if audio_url:
        audio_url = "%s%s" % ("http://mp3.meirtv.co.il/", audio_url)
    if not video_url and not audio_url:
        print("missing audio and video")
        return False
    category = get_hash_for_id(source_id, get_original_category_id(lesson))
    rav_id = get_original_rav_id(lesson)
    if rav_id != 0:
        rav_id = get_hash_for_id(source_id, rav_id)
    body = {
        "id": id,
        "sourceId": source_id,
        "originalId": original_id,
        "title": lesson["post_title"],
        "categoryId": category,
        "seriesId": get_hash_for_id(source_id, original_series_id),
        "ravId": rav_id,
        "dateStr": get_heb_date(date_time_obj),
        "duration": duration,
        "videoUrl": video_url,
        "audioUrl": audio_url,
        "timestamp": timestamp,
    }
    add_lesson_to_db(cursor, body)
    exists_original_ids.append(original_id)
    return True, id
    # print(body)


def get_original_series_id(lesson: dict) -> int:
    global with_no_series, sets_arr
    key_name = "shiurim-series"
    if key_name not in lesson:
        key_name = "shiurim-tags"
        if key_name not in lesson:
            return 0
    entry = lesson[key_name][0]
    if check_int(entry["slug"]):
        original_series_id = int(entry['slug'])
    else:
        original_series_id = int(entry['term_id'])
    if original_series_id in sets_arr:
        pass
    else:
        with_no_series.add(original_series_id)
        print("!missing set ", original_series_id)
        cursor = postgres.cursor()
        add_missing_serie_id(cursor, original_series_id, entry['name'])
        cursor.close()
        postgres.commit()
    return original_series_id


def get_original_category_id(lesson: dict) -> int:
    global categories_ids
    if "shiurim-category" not in lesson:
        if 'mador' in lesson and lesson['mador'][0]['term_id'] != 13305:
            entry = lesson['mador'][0]
        else:
            return 3786
    else:
        entry = lesson["shiurim-category"][0]
    if check_int(entry["slug"]):
        category_id = int(entry['slug'])
    else:
        category_id = int(entry['term_id'])
    if category_id in categories_ids:
        pass
    else:
        print("!missing category ", category_id)
        cursor = postgres.cursor()
        add_missing_category_id(cursor, category_id, entry['name'])
        cursor.close()
        postgres.commit()
    return category_id


def get_original_rav_id(lesson: dict) -> int:
    global ravs_arr
    if "rabbis" not in lesson:
        print("missing rav", lesson)
        return 0
    rav = lesson["rabbis"][0]['slug']
    if not check_int(rav):
        rav = lesson["rav_1_id"][0]
        if not check_int(rav):
            rav = lesson["rabbis"][0]['slug']
            rav_id = rav.split("-")[1]
            if check_int(rav_id):
                rav = rav_id
            else:
                rav = lesson["rabbis"][0]['term_id']
    rav = int(rav)
    if rav in ravs_arr:
        pass
    else:
        print("!missing rav ", rav)
        cursor = postgres.cursor()
        add_missing_rav_id(cursor, rav, lesson["rabbis"][0]['name'])
        cursor.close()
        postgres.commit()
    return rav


flag_api = True


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
    except Exception as e:
        print(first, ' couldn"t grab %s' % vimeo_url % vimeo_id, "bearer %s" % api, )
        flag_api = not flag_api
        # traceback.print_exc()
        return get_video_url(vimeo_id, False) if first else None


def check_int(str_int):
    if not str_int:
        return False
    try:
        int(str_int)
        return True
    except ValueError:
        return False


def grab_meir_main():
    extract_lessons_for_channel_id(2, "UCEAZVyOtukIOH4BJ3gHKdng", "ערוץ מאיר-יוטיוב", "ערוץ מאיר - יוטיוב")
    # grab_page(is_main_page=True)


if __name__ == '__main__':
    # grab()
    # cursor = postgres.cursor()
    # add_missing_serie_id(cursor, 0, 'ללא')
    # add_missing_category_id(cursor, 3786, 'כללי')
    # cursor.close()
    # postgres.commit()
    # grab_page(1184)
    extract_lessons_for_channel_id(2, "UCEAZVyOtukIOH4BJ3gHKdng", "ערוץ מאיר-יוטיוב", "ערוץ מאיר - יוטיוב")
    # grab_page(is_main_page=True)
    # grab_for_serie()
    # http://player.vimeo.com/external/335685696.hd.mp4?s=3fe2de2efc420884a4f6c13d0986e0cb2255a062&profile_id=175&oauth2_token_id=1009673393

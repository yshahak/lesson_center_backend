import hashlib
import datetime
import re


def get_hash_for_id(source_id: int, originalid: int) -> int:
    hash_object = hashlib.md5(('%s_%s' % (source_id, originalid,)).encode())
    return int(hash_object.hexdigest(), 16) % 10 ** 8


def get_timestamp():
    return int((datetime.datetime.utcnow() - datetime.datetime(1970, 1, 1)).total_seconds())


def get_duration_in_seconds(duration: str):
    if not duration:
        return 0
    try:
        correct = re.sub('[^0-9:]', "", duration)
        while len(correct.split(':')) < 3:
            correct = "00:%s" % correct
        h, m, s = correct.split(':')
        return int(datetime.timedelta(hours=int(h), minutes=int(m), seconds=int(s)).total_seconds())
    except:
        print('duration issue!!:', duration)
        return 0


def clear_labels(postgres, source_id):
    cursor = postgres.cursor()
    cursor.execute('''DELETE FROM labels WHERE sourceid = %s;''', (source_id,))
    postgres.commit()


def add_lesson_to_db(cursor, now, body):
    cursor.execute('''
    insert into lessons(
    id,sourceid,originalid,title,categoryid,seriesid,ravid,videourl,audiourl,datestr,duration,"timestamp",insertedat,updatedat)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT(id)
    DO NOTHING 
    --UPDATE SET
    --updatedat = %s;
    ''', (
        body["id"], body["sourceid"], body["originalid"], body["title"],
        body["categoryid"], body["seriesId"], body["ravId"],
        body["videoUrl"], body["audioUrl"],
        body["dateStr"], body["duration"],
        body["timestamp"], now, now, now))



month_dict = {
    u'תשרי': 7,
    u'חשון': 8,
    u'חשוון': 8,
    u'כסלו': 9,
    u'טבת': 10,
    u'שבט': 11,
    u'אדר': 12,
    u'אדר א': 12,
    u'אדר ב': 13,
    u'ניסן': 1,
    u'אייר': 2,
    u'איר': 2,
    u'סיון': 3,
    u'סיוון': 3,
    u'תמוז': 4,
    u'אב': 5,
    u'אלול': 6,
}
gimatria_map = {
    u'': 0,
    u'א': 1,
    u'ב': 2,
    u'ג': 3,
    u'ד': 4,
    u'ה': 5,
    u'ו': 6,
    u'ז': 7,
    u'ח': 8,
    u'ט': 9,
    u'י': 10,
    u'כ': 20,
    u'ל': 30,
    u'מ': 40,
    u'נ': 50,
    u'ס': 60,
    u'ע': 70,
    u'פ': 80,
    u'צ': 90,
    u'ק': 100,
    u'ר': 200,
    u'ש': 300,
    u'ת': 400,
}

day_list = [
    u' ',
    u'א',
    u'ב',
    u'ג',
    u'ד',
    u'ה',
    u'ו',
    u'ז',
    u'ח',
    u'ט',
    u'י',
    u'יא',
    u'יב',
    u'יג',
    u'יד',
    u'טו',
    u'טז',
    u'יז',
    u'יח',
    u'יט',
    u'כ',
    u'כא',
    u'כב',
    u'כג',
    u'כד',
    u'כה',
    u'כו',
    u'כז',
    u'כח',
    u'כט',
    u'ל',
]

month_dict = {value: key for key, value in month_dict.items()}
gimatria_map = {value: key for key, value in gimatria_map.items()}

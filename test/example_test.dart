import 'dart:convert';

import 'harness/app.dart';

var str = '''
[
  {
    "id": 2647,
    "title": "תניא 36 פרק ל'-לא' ",
    "label": "myLabel",
    "subjectId": 1,
    "subject": "אנשי אמונה בעולם המעשה",
    "seriesId": 5,
    "series": "תניא - הרב חיים וידל",
    "ravId": 19,
    "rav": "הרב חיים וידאל",
    "dateStr": "כ בתמוז תשסח",
    "length": "55:45",
    "videoUrl": null,
    "audioUrl": "http://bneidavidmp3.media-line.co.il/bneidavid/vf/audio/2647/TANIA%2036-hAREV%20CHAIM.mp3",
    "timestamp": 1216684800,
    "source": "Bnei David"
  },
  {
    "id": 10714,
    "title": "תיקון הפירוד שהחל במכירת יוסף -הרב ברוך רוזנבלום | פורים",
    "label": "myLabel",
    "subjectId": 33,
    "subject": "שבת ומועדים",
    "seriesId": 1,
    "series": "ללא       ",
    "ravId": 37,
    "rav": "כללי",
    "dateStr": "ו באדר ב תשעו",
    "length": "58:35",
    "videoUrl": "http://users.media-line.co.il/bneidavid/vf/audio/video/klali/rozenbluom_porim5776.mp4",
    "audioUrl": "http://bneidavidmp3.media-line.co.il/bneidavid/vf/audio/klali/rozenbluom_porim5776.mp3",
    "timestamp": 1458086400,
    "source": "Bnei David"
  },
  {
    "id": 13175,
    "title": "חג הסוכות בימי עזרא - קו פרשת המים לתורה שבע''פ | הרב אליקים לבנון - לימוד ליל הושענא רבא",
    "label": "myLabel",
    "subjectId": 33,
    "subject": "שבת ומועדים",
    "seriesId": 1,
    "series": "ללא       ",
    "ravId": 37,
    "rav": "כללי",
    "dateStr": "כא בתשרי תשעח",
    "length": "1:01:10",
    "videoUrl": "http://users.media-line.co.il/bneidavid/vf/audio/video/klali/levanon_HoshanaRaba_SokotToraShbalPe5778.mp4",
    "audioUrl": "http://bneidavidmp3.media-line.co.il/bneidavid/vf/audio/klali/levanon_HoshanaRaba_SokotToraShbalPe5778.mp3",
    "timestamp": 1507593600,
    "source": "Bnei David"
  }
]
''';

var single = '''
[
{
    "id": 13175,
    "title": "חג הסוכות בימי עזרא - קו פרשת המים לתורה שבע''פ | הרב אליקים לבנון - לימוד ליל הושענא רבא",
    "label": "myLabel",
    "subjectId": 33,
    "subject": "שבת ומועדים",
    "seriesId": 1,
    "series": "ללא       ",
    "ravId": 37,
    "rav": "כללי",
    "dateStr": "כא בתשרי תשעח",
    "length": "1:01:10",
    "videoUrl": "http://users.media-line.co.il/bneidavid/vf/audio/video/klali/levanon_HoshanaRaba_SokotToraShbalPe5778.mp4",
    "audioUrl": "http://bneidavidmp3.media-line.co.il/bneidavid/vf/audio/klali/levanon_HoshanaRaba_SokotToraShbalPe5778.mp3",
    "timestamp": 1507593600,
    "source": "Bnei David"
  }
  ]
''';

Future main() async {
  final harness = Harness()..install();

//  test("POST /lessons returns 200 {'key': 'value'}", () async {
//    expectResponse(await harness.agent.post("/lessons", body: json.decode(str)), 200, body: {"key": "value"});
//  });
//  test("POST /lessons returns 200 {'key': 'value'}", () async {
//    expectResponse(await harness.agent.post("/lessons", body: json.decode(single)), 200, body: {"key": "value"});
//  });
//  test("GET /endpoint returns 200 and a simple object", () async {
//    final response = await harness.agent.get("/seed/bneidavid");
//    expect(true, (response.body.as<Map>()["bneidavid"] as List).isNotEmpty);
//  });
  test("GET /endpoint returns 200 and a simple object", () async {
    final response = await harness.agent.get("/seed/dal");
    expect("true", response.body.as<Map>()["dal"] as String);
  });
}

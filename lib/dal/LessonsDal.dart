import 'package:lesson_center_backend/lesson_center_backend.dart';
import 'package:lesson_center_backend/model/Lesson.dart';
import 'package:lessons_center_common/lessons_center_common.dart' as common;

class LessonsDal {

  static Future<List> insertLessons(ManagedContext context, List<Lesson> lessons) async {
    final nowInMs = DateTime.now().millisecondsSinceEpoch;
    final ids = List();
    for (var lesson in lessons) {
      Lesson insertedLesson;
      try {
        final lessonQuery = Query<Lesson>(context)
          ..values = lesson
          ..values.insertedAt = nowInMs
          ..values.updatedAt = nowInMs;
        insertedLesson = await lessonQuery.insert();
        ids.add(insertedLesson.id);
      } on QueryException catch (_) {
        final updateQuery = Query<Lesson>(context)
          ..values = lesson
          ..values.updatedAt = nowInMs
          ..where((h) => h.id).equalTo(lesson.id);
        insertedLesson = (await updateQuery.update())[0];
        ids.add(insertedLesson.id);
      }
      print(insertedLesson);
    }
    return ids;
  }

  static Future<List> insertCommonLessons(ManagedContext context, List<common.Lesson> lessons) async {
    final ids = List();
    for (var lesson in lessons) {
      Lesson insertedLesson;
      try {
        final lessonQuery = Query<Lesson>(context)
          ..values.id = lesson.id
          ..values.title = lesson.title
          ..values.label = lesson.label
          ..values.subjectId = lesson.subjectId
          ..values.subject = lesson.subject
          ..values.seriesId = lesson.seriesId
          ..values.series = lesson.series
          ..values.dateStr = lesson.dateStr
          ..values.ravId = lesson.ravId
          ..values.rav = lesson.rav
          ..values.length = lesson.length
          ..values.videoUrl = lesson.videoUrl
          ..values.audioUrl = lesson.audioUrl
          ..values.timestamp = lesson.timestamp
          ..values.source = lesson.source;
        insertedLesson = await lessonQuery.insert();
        ids.add(insertedLesson.id);
      } on QueryException catch (_) {
        final updateQuery = Query<Lesson>(context)
          ..values.id = lesson.id
          ..values.title = lesson.title
          ..values.label = lesson.label
          ..values.subjectId = lesson.subjectId
          ..values.subject = lesson.subject
          ..values.seriesId = lesson.seriesId
          ..values.series = lesson.series
          ..values.dateStr = lesson.dateStr
          ..values.ravId = lesson.ravId
          ..values.rav = lesson.rav
          ..values.length = lesson.length
          ..values.videoUrl = lesson.videoUrl
          ..values.audioUrl = lesson.audioUrl
          ..values.timestamp = lesson.timestamp
          ..values.source = lesson.source
          ..where((h) => h.id).equalTo(lesson.id);
        insertedLesson = (await updateQuery.update())[0];
        ids.add(insertedLesson.id);
      }
      print(insertedLesson);
    }
    return ids;
  }

  Future convertPsqlToSqlite(ManagedContext context) async{
    final lessonQuery = Query<Lesson>(context);
    final lessons = await lessonQuery.fetch();
  }
}

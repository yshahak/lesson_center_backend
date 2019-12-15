import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/dal/LessonsDal.dart';
import 'package:lesson_center_backend/model/Lesson.dart';




class LessonController extends ResourceController {

  LessonController(this.context);

  final ManagedContext context;

  @Operation.get('id')
  Future<Response> getLessonByID(@Bind.path('id') int id) async {
    final lessonQuery = Query<Lesson>(context)
      ..where((h) => h.id).equalTo(id);

    final lesson = await lessonQuery.fetchOne();
    if (lesson == null) {
      return Response.notFound();
    }
    return Response.ok(lesson);
  }

  @Operation.get()
  Future<Response> getAllLessonsByTimestamp({@Bind.query('timestamp') String timestamp}) async {
    final lessonQuery = Query<Lesson>(context);
    timestamp ??= "-1";
    lessonQuery.where((record) => record.insertedAt).greaterThanEqualTo(int.parse(timestamp));
    final lessons = await lessonQuery.fetch();
    final response = Response.ok(lessons);
    final general = File("general.json");
    final lastRun = (json.decode(general.readAsStringSync()) as Map)['last_run'] as int;
    response.headers['ts'] = lastRun;
    return response;
  }

//  @Operation.get()
//  Future<Response> getAllLessons({@Bind.query('title') String title}) async {
//    final lessonQuery = Query<Lesson>(context);
//    if (title != null) {
//      lessonQuery.where((record) => record.title).contains(title, caseSensitive: false);
//    }
//    final lessons = await lessonQuery.fetch();
//    return Response.ok(lessons);
//  }

  @Operation.get('subject')
  Future<Response> getLessonBySubject(@Bind.path('subject') String subject) async {
    final lessonQuery = Query<Lesson>(context)
      ..where((h) => h.subject).equalTo(subject);
    final lesson = await lessonQuery.fetchOne();
    if (lesson == null) {
      return Response.notFound();
    }
    return Response.ok(lesson);
  }

  @Operation.post()
  Future<Response> seedLessons(@Bind.body() List<Lesson> lessons) async {
    final ids = await LessonsDal.insertLessons(context, lessons);
    return Response.ok({"key": "value"});
  }

//  @Operation.delete()
//  Future<Response> deleteAll() async {
//    final lessonQuery = Query<Lesson>(context)
//      ..where((u) => u.id).notEqualTo(-200);
//    final insertedLesson = await lessonQuery.delete();
//    return Response.ok(insertedLesson);
//  }

}

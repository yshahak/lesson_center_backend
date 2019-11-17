import 'dart:async';

import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/dal/LessonsDal.dart';
import 'package:lesson_center_backend/model/Lesson.dart';




class LessonController extends ResourceController {

  LessonController(this.context);

  final ManagedContext context;

  @Operation.get()
  Future<Response> getAllLessons({@Bind.query('title') String title}) async {
    final lessonQuery = Query<Lesson>(context);
    if (title != null) {
      lessonQuery.where((record) => record.title).contains(title, caseSensitive: false);
    }
    final lessons = await lessonQuery.fetch();
    return Response.ok(lessons);
  }

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

//  @Operation.post()
//  Future<Response> createLesson() async {
//    print('createLesson called');
//    final newLesson = Lesson()
//      ..read(await request.body.decode());
//    print(newLesson);
//    final lessonQuery = Query<Lesson>(context)
//      ..values = newLesson;
//    try {
//      final insertedLesson = await lessonQuery.insert();
//      return Response.ok(insertedLesson);
//    } on QueryException catch (e) {
//      print(e);
//      final updateQuery = Query<Lesson>(context)
//          ..values = newLesson
//        ..where((h) => h.id).equalTo(newLesson.id);
//      final insertedLesson = await updateQuery.update();
//      return Response.ok(insertedLesson);
//    }
//  }

  @Operation.delete()
  Future<Response> deleteAll() async {
    final lessonQuery = Query<Lesson>(context)
      ..where((u) => u.id).notEqualTo(-200);
    final insertedLesson = await lessonQuery.delete();
    return Response.ok(insertedLesson);
  }

}

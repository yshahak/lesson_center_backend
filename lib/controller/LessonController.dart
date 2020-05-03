import 'dart:async';
import 'dart:io';

import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/model/Lesson.dart';

class LessonController extends ResourceController {
  LessonController(this.context);

  final ManagedContext context;

  @Operation.get('id')
  Future<Response> getLessonByID(@Bind.path('id') int id) async {
    final lessonQuery = Query<Lesson>(context)..where((h) => h.id).equalTo(id);
    final lesson = await lessonQuery.fetchOne();
    if (lesson == null) {
      return Response.notFound();
    }
    return Response.ok(lesson);
  }

  @Operation.get()
  Future<Response> getAllLessonsByTimestamp(
      {@Bind.query('timestamp') String timestamp, @Bind.query('page') String page,
        @Bind.query('limit') String limit, @Bind.query('source') String sourceId,
        @Bind.query('rav') String rav, @Bind.query('category') String category,
        @Bind.query('serie') String serie, @Bind.query('title') String title}) async {
    timestamp ??= "0";
    page ??= "1";
    limit ??= "200";
    final offset = (int.parse(page) - 1) * int.parse(limit);
    print('$timestamp\t$page\t$limit\t$sourceId\toffset=$offset');
    final lessonQuery = Query<Lesson>(context)
      ..where((record) => record.updatedAt).greaterThan(int.parse(timestamp))
      ..sortBy((record) => record.updatedAt, QuerySortOrder.descending)
      ..sortBy((record) => record.timestamp, QuerySortOrder.descending)
      ..fetchLimit = int.parse(limit)
      ..offset = offset;
    if (sourceId != null){
      lessonQuery.where((record) => record.sourceId).equalTo(int.parse(sourceId));
    }
    if (title != null) {
      lessonQuery.where((record) => record.title).like('%$title%');
    }
    if (category != null){
      lessonQuery.where((record) => record.categoryId).equalTo(int.parse(category));
    }
    if (serie != null){
      lessonQuery.where((record) => record.seriesId).equalTo(int.parse(serie));
    }
    if (rav != null){
      lessonQuery.where((record) => record.ravId).equalTo(int.parse(rav));
    }
    final lessons = await lessonQuery.fetch();
    final query = Query<Lesson>(context);
    final lastRun = await query.reduce.maximum((u) => u.updatedAt);

    final body = {
      "lessons": lessons.map((l) => l.asMap()).toList(),
      "ts": lastRun,
    };
    final response = Response.ok(body)..contentType = ContentType.json;
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

//  @Operation.get('subject')
//  Future<Response> getLessonBySubject(@Bind.path('subject') String subject) async {
//    final lessonQuery = Query<Lesson>(context)..where((h) => h.subject).equalTo(subject);
//    final lesson = await lessonQuery.fetchOne();
//    if (lesson == null) {
//      return Response.notFound();
//    }
//    return Response.ok(lesson);
//  }

//  @Operation.post()
//  Future<Response> seedLessons(@Bind.body() List<Lesson> lessons) async {
//    final ids = await LessonsDal.insertLessons(context, lessons);
//    return Response.ok({"key": "value"});
//  }

//  @Operation.delete()
//  Future<Response> deleteAll() async {
//    final lessonQuery = Query<Lesson>(context)
//      ..where((u) => u.id).notEqualTo(-200);
//    final insertedLesson = await lessonQuery.delete();
//    return Response.ok(insertedLesson);
//  }

}

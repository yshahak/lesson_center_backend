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
    final dateTimeTS = DateTime.fromMillisecondsSinceEpoch(int.parse(timestamp));
    final lessonQuery = Query<Lesson>(context)
      ..where((record) => record.updatedat).greaterThan(dateTimeTS)
      // ..sortBy((record) => record.updatedat, QuerySortOrder.descending)
      ..sortBy((record) => record.timestamp, QuerySortOrder.descending)
      ..fetchLimit = int.parse(limit)
      ..offset = offset;
    if (sourceId != null){
      lessonQuery.where((record) => record.sourceid).equalTo(int.parse(sourceId));
    }
    if (title != null) {
      lessonQuery.where((record) => record.title).like('%$title%');
    }
    if (category != null){
      lessonQuery.where((record) => record.categoryid).equalTo(int.parse(category));
    }
    if (serie != null){
      lessonQuery.where((record) => record.seriesid).equalTo(int.parse(serie));
    }
    if (rav != null){
      lessonQuery.where((record) => record.ravid).equalTo(int.parse(rav));
    }
    final lessons = await lessonQuery.fetch();
    final query = Query<Lesson>(context);
    final lastRun = (await query.reduce.maximum((u) => u.updatedat)).millisecondsSinceEpoch;

    final body = {
      "lessons": lessons.map((l) => {
        "id": l.id,
        "originalId": l.originalid,
        "sourceId": l.sourceid,
        "title": l.title,
        "categoryId": l.categoryid,
        "seriesId": l.seriesid,
        "ravId": l.ravid,
        "dateStr": l.datestr,
        "duration": l.duration,
        "videoUrl": l.videourl,
        "audioUrl": l.audiourl,
        "timestamp": l.timestamp,
      }).toList(),
      "ts": lastRun,
    };
    final response = Response.ok(body)..contentType = ContentType.json;
    response.headers['ts'] = lastRun;
    return response;
  }
}

import 'dart:async';
import 'dart:io';

import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/model/Label.dart';
import 'package:lesson_center_backend/model/Lesson.dart';

class LabelsController extends ResourceController {
  LabelsController(this.context);

  final ManagedContext context;

  @Operation.get()
  Future<Response> getLabels({@Bind.query('source') String sourceId}) async {
    final mainPage = Query<Label>(context);
    if (sourceId != null) {
      mainPage.where((record) => record.sourceid).equalTo(int.parse(sourceId));
    }
    final labels = await mainPage.fetch();
    var body = {};
    if (labels.isNotEmpty) {
      final ids = labels.map((e) => e.lessonid);
      final lessonQuery = Query<Lesson>(context)..where((record) => record.id).oneOf(ids);
      final lessons = await lessonQuery.fetch();
      //we add lessons to make sure the client will have the lessons in it database
      body = {
        "mainPage": labels.map((l) => {
          "id": l.id,
          "sourceId": l.sourceid,
          "lessonId": l.lessonid,
          "label": l.label,
        }).toList(),
        // "lessons": lessons.map((l) => l.asMap()).toList(),
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
      };
    } else {
      body = {
        "mainPage": [],
        "lessons": [],
      };
    }

    final response = Response.ok(body)..contentType = ContentType.json;
    return response;
  }
}

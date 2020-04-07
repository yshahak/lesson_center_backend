import 'dart:async';
import 'dart:io';

import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/model/Label.dart';
import 'package:lesson_center_backend/model/Lesson.dart';

class LabelsController extends ResourceController {
  LabelsController(this.context);

  final ManagedContext context;

  @Operation.get()
  Future<Response> getLabels() async {
    final mainPage = Query<Label>(context);
    final labels = await mainPage.fetch();
    final ids = labels.map((e) => e.lessonId);
    final lessonQuery = Query<Lesson>(context)
      ..where((record) => record.id).oneOf(ids);
    final lessons = await lessonQuery.fetch();
    final body = {
      "mainPage": labels.map((l) => l.asMap()).toList(),
      "lessons": lessons.map((l) => l.asMap()).toList(),
    };
    final response = Response.ok(body)..contentType = ContentType.json;
    return response;
  }
}

import 'dart:async';
import 'package:aqueduct/aqueduct.dart';
import 'package:lesson_center_backend/dal/LessonsDal.dart';
import 'package:lessons_center_common/lessons_center_common.dart';

class SeedController extends ResourceController {

  SeedController(this.context);

  final ManagedContext context;

  @Operation.get('source')
  Future<Response> seedSource(@Bind.path('source') String source) async {
    if (source == 'bneidavid'){
      final lessons = await getLessonsFromUrl(true, "http://www.bneidavid.org/Web/He/VirtualTorah/Lessons/Default.aspx");
      final ids = await LessonsDal.insertCommonLessons(context, lessons);
      return Response.ok({source: ids});
    } else {
      return Response.ok({source: []});

    }
    return Response.ok({source: []});
  }


}

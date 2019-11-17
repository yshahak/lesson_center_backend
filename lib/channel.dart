import 'package:lesson_center_backend/controller/LessonController.dart';
import 'package:lesson_center_backend/controller/SeedController.dart';

import 'lesson_center_backend.dart';

class LessonCenterBackendChannel extends ApplicationChannel {
  var conn = '''
  postgres=# CREATE DATABASE lessons;
  CREATE DATABASE
  postgres=# CREATE USER yaakov WITH createdb;
  CREATE ROLE
  postgres=# alter user yaakov WITH password '1234';
  ALTER ROLE
  
  RESETING DB:
  1. drop table lessons;
  2. drop table _aqueduct_version_pgsql;
  ''';

  ManagedContext context;

  @override
  Future prepare() async {
    logger.onRecord.listen((rec) => print("$rec ${rec.error ?? ""} ${rec.stackTrace ?? ""}"));
    final dataModel = ManagedDataModel.fromCurrentMirrorSystem();
    final persistentStore = PostgreSQLPersistentStore.fromConnectionInfo("yaakov", "4431", "localhost", 5432, "lessons");

    context = ManagedContext(dataModel, persistentStore);
  }

  @override
  Controller get entryPoint {
    final router = Router();

    router.route('/lessons/[:id]').link(() => LessonController(context));

    router.route('/seed/[:source]').link(() => SeedController(context));

    return router;
  }
}

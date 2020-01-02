import 'dart:convert';

import 'package:lesson_center_backend/controller/LessonController.dart';

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
  
  aqueduct db generate
  aqueduct db upgrade --connect postgres://yaakov:1234@localhost:5432/lessons
  ''';

  ManagedContext context;

  @override
  Future prepare() async {
    logger.onRecord.listen((rec) => print("$rec ${rec.error ?? ""} ${rec.stackTrace ?? ""}"));

    final config = MyConfiguration(options.configurationFilePath);

    final dataModel = ManagedDataModel.fromCurrentMirrorSystem();
//    final persistentStore = PostgreSQLPersistentStore.fromConnectionInfo("yaakov", "1234", "localhost", 5432, "lessons");
    final persistentStore = PostgreSQLPersistentStore.fromConnectionInfo(config.database.username,
        config.database.password,
        config.database.host,
        config.database.port,
        config.database.databaseName);

    context = ManagedContext(dataModel, persistentStore);
  }

  @override
  Controller get entryPoint {
    final router = Router();

    router.route('/lessons/[:id]').link(() => LessonController(context));

    router.route("/files/*").link(() => FileTimeStamp()).link(() => FileController("files/public/"));

    return router;
  }
}
class FileTimeStamp extends Controller {

  @override
  Future<RequestOrResponse> handle(Request request) async {
    request.addResponseModifier((response) {
      final general = File("general.json");
      final lastRun = (json.decode(general.readAsStringSync()) as Map)['last_run'] as int;
      response.headers["timestamp"] = lastRun;
    });

    return request;
  }
}

class MyConfiguration extends Configuration {
  MyConfiguration(String configPath) : super.fromFile(File(configPath));

  DatabaseConfiguration database;
}

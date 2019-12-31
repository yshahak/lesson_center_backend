import 'dart:convert';

import 'harness/app.dart';

Future main() async {
  final harness = Harness()..install();

  test("GET /endpoint returns lessons for ts", () async {
    final response = await harness.agent.get("/lessons?timestamp=100");
    expect(response.statusCode, 200);
    expect(true, (response.body.as<Map>()['lessons']).isNotEmpty);
    expect(true, (response.body.as<Map>()['mainPage']).isNotEmpty);
    final ts = int.parse(response.headers.value('ts'));
    final general = File("general.json");
    final lastRun = (json.decode(general.readAsStringSync()) as Map)['last_run'] as int;
    expect(lastRun, ts);
    expect(lastRun, response.body.as<Map>()['ts'] as int);
  });
}
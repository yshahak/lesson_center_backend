import 'dart:convert';

import 'harness/app.dart';

Future main() async {
  final harness = Harness()..install();

  test("GET /endpoint returns lessons for ts", () async {
    final response = await harness.agent.get("/lessons?timestamp=0&page=1");
    expect(response.statusCode, 200);
    expect(true, (response.body.as<Map>()['lessons']).isNotEmpty);
  });
}
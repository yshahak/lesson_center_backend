import 'dart:convert';

import 'harness/app.dart';

Future main() async {
  final harness = Harness()..install();

  test("GET /endpoint returns labels for ts", () async {
    final response = await harness.agent.get("/labels?source=1");
    expect(response.statusCode, 200);
  });
}
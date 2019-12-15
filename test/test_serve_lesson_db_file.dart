import 'harness/app.dart';

Future main() async {
  final harness = Harness()..install();

//  test("POST /lessons returns 200 {'key': 'value'}", () async {
//    expectResponse(await harness.agent.post("/lessons", body: json.decode(str)), 200, body: {"key": "value"});
//  });
//  test("POST /lessons returns 200 {'key': 'value'}", () async {
//    expectResponse(await harness.agent.post("/lessons", body: json.decode(single)), 200, body: {"key": "value"});
//  });
//  test("GET /endpoint returns 200 and a simple object", () async {
//    final response = await harness.agent.get("/seed/bneidavid");
//    expect(true, (response.body.as<Map>()["bneidavid"] as List).isNotEmpty);
//  });
  test("GET /endpoint returns 200 and a file", () async {
    final response = await harness.agent.get("/files/lessons.db");
    expect(response.statusCode, 200);
  });
}
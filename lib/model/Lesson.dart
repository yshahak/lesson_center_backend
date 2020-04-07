import 'package:aqueduct/aqueduct.dart';

class Lesson extends ManagedObject<Lessons> implements Lessons {}

class Lessons {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.bigInteger, autoincrement: false)
  int id;
  @Column(nullable: false)
  int sourceId;
  @Column(nullable: false)
  int originalId;
  @Column(nullable: false)
  String title;
  @Column(nullable: true)
  int categoryId;
  @Column(nullable: true)
  int seriesId;
  @Column(nullable: true)
  String dateStr;
  @Column(nullable: true)
  int ravId;
  @Column(nullable: true)
  int duration;
  @Column(nullable: true)
  String videoUrl;
  @Column(nullable: true)
  String audioUrl;
  @Column(nullable: true)
  int timestamp;
  @Column(nullable: true)
  int insertedAt;
  @Column(nullable: false)
  int updatedAt;
}
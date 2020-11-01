import 'package:aqueduct/aqueduct.dart';

class Lesson extends ManagedObject<Lessons> implements Lessons {}

class Lessons {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.integer, autoincrement: false)
  int id;
  @Column(nullable: false)
  int sourceid;
  @Column(nullable: false)
  int originalid;
  @Column(nullable: false)
  String title;
  @Column(nullable: true)
  int categoryid;
  @Column(nullable: true)
  int seriesid;
  @Column(nullable: true)
  String datestr;
  @Column(nullable: true)
  int ravid;
  @Column(nullable: true)
  int duration;
  @Column(nullable: true)
  String videourl;
  @Column(nullable: true)
  String audiourl;
  @Column(nullable: false)
  int timestamp;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime insertedat;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime updatedat;
}
import 'package:aqueduct/aqueduct.dart';

class Label extends ManagedObject<Labels> implements Labels {}

class Labels {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.integer, autoincrement: true)
  int id;
  @Column(nullable: false)
  String label;
  @Column(nullable: false)
  int sourceId;
  @Column(nullable: false)
  int lessonId;

}

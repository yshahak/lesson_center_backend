import 'package:aqueduct/aqueduct.dart';

class Serie extends ManagedObject<Series> implements Series {}

class Series {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.bigInteger, autoincrement: false)
  int id;
  @Column(nullable: false)
  int originalId;
  @Column(nullable: false)
  int sourceId;
  @Column(nullable: false)
  int totalCount;
  @Column(nullable: false)
  String serie;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime insertedat;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime updatedat;
}

import 'package:aqueduct/aqueduct.dart';

class Rav extends ManagedObject<Ravs> implements Ravs {}

class Ravs {

  @Column(primaryKey: true, unique: true, databaseType: ManagedPropertyType.bigInteger, autoincrement: false)
  int id;
  @Column(nullable: false)
  int originalId;
  @Column(nullable: false)
  int sourceId;
  @Column(nullable: false)
  int totalCount;
  @Column(nullable: false)
  String rav;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime insertedat;
  @Column(nullable: false, databaseType: ManagedPropertyType.datetime)
  DateTime updatedat;
}

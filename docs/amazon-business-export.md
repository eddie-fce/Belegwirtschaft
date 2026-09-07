# Amazon Business — Rechnungen einsammeln (manuell, 1–2× im Jahr)

Kein eigener Connector nötig: Amazon Business hat einen eingebauten
Sammel-Export für Rechnungen, der bis zu 5 Jahre rückwirkend und bis zu 2000
Dokumente pro Durchgang abdeckt. Ein API-Zugang (Entwicklerregistrierung bei
Amazon) oder eine Browser-Automatisierung gegen Amazons UI würden hier nur
Komplexität für etwas hinzufügen, das ohnehin nur selten anfällt.

## Ablauf

1. Bei business.amazon.de einloggen, oben im Konto-Menü **"Business
   Analytics"** öffnen.
2. Im Reiter **"Berichte"** den Bericht **"Bestellungen"** wählen, Zeitraum
   auf das gewünschte Jahr (oder mehrere Jahre rückwirkend) einstellen.
3. Bestellungen auswählen (oder alle) → **"Auftragsdokumente abrufen"** bzw.
   "Get order documents" → **Rechnungen** auswählen → herunterladen. Amazon
   liefert ein ZIP mit allen Rechnungs-PDFs.
4. Das ZIP entpacken und die PDFs in `./data/dropzone/eingang/` legen (Amazon-
   Einkäufe sind Eingangsrechnungen) — der
   [Dropzone-Connector](../connectors/dropzone/README.md) lädt sie
   automatisch mit Tag `Manuell` nach Docspell hoch. Docspell dedupliziert
   identische Dateien serverseitig per Hash, ein erneuter Export mit
   Überschneidung zum Vorjahr schadet also nicht.

## Warum kein automatisierter Connector?

Zwei Gründe, aus denen bewusst kein Code dafür existiert:
- **Ohne Amazon-Entwicklerzugang** gibt es keine stabile API-Automatisierung.
- **Bei 1–2 Exporten im Jahr** lohnt sich eine (ohnehin nur geschätzte,
  ungetestete) Browser-Automatisierung gegen Amazons UI nicht — der aus ein
  paar Klicks bestehende manuelle Weg ist zuverlässiger als ein Bot, der bei
  der nächsten Amazon-Layout-Änderung lautlos aufhört zu funktionieren, und
  muss nicht gewartet werden.

Falls sich das später ändert (z.B. Amazon-Entwicklerzugang wird doch
möglich), lohnt sich ein neuer, gezielt gebauter und gegen die dann aktuelle
Doku getesteter Connector — Details dazu gerne wieder anfragen.

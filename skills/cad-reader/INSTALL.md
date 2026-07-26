# Установка ODA File Converter (для DWG -> DXF)

## Шаги (Windows)

1. Зарегистрируйся (бесплатно) и скачай:
   - https://www.opendesign.com/guestfiles/oda_file_converter

2. Бери Windows 64-bit installer (`ODAFileConverter_QT5_vc14dll_25.4_x64.exe` или новее).

3. Установи в путь по умолчанию: `C:\Program Files\ODA\ODAFileConverter <версия>\`.

4. Проверь:
   ```bash
   python -c "
   import sys
   sys.path.insert(0, '.agents/skills/cad-reader/scripts')
   from dwg_to_dxf import find_oda_executable
   print(find_oda_executable())
   "
   ```

## Текущий статус (<организация>)

ODA File Converter 27.1.0 установлен в:
`C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe`

## Альтернативы

### LibreCAD (только просмотр)
- https://librecad.org/

### Aspose.CAD (платный, более стабильный CLI)
- https://products.aspose.com/cad/python-net/

### Если DWG напрямую не нужен
- Попроси заказчика DXF (открытый формат) или PDF чертёж

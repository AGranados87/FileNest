import os
import shutil

#RUTA DE LOS ARCHIVOS A ORDENAR
ruta = "C:/Users/agran/OneDrive/Escritorio/auto_python"

#CREAR LAS CARPETAS EN EL CASO DE QUE NO EXISTAN PARA ORGANIZAR LOS ARCHIVOS

tipos=["Imágenes", "PDFs", "Vídeos", "Documentos Word", "Excel", "Texto"]

for carpeta in tipos:
    rutaCarpeta = os.path.join(ruta, carpeta)

    if not os.path.exists(rutaCarpeta):
        os.makedirs(rutaCarpeta)




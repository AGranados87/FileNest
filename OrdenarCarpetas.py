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

#POR CADA ARCHIVO QUE SE ENCUENTRE, MUEVELO A LA CARPETA CORRESPONDIENTE

for archivo in os.listdir(ruta):
    if archivo.endswith(".pdf"):
        shutil.move(os.path.join(ruta, archivo), os.path.join(ruta, "PDFs", archivo))

    elif archivo.endswith(".docx"):
        shutil.move(os.join(ruta, archivo), os.path.join(ruta, "Documentos Word", archivo))

    elif archivo.endswith(".txt"):
        shutil.move(os.join(ruta, archivo), os.path.join(ruta, "Texto", archivo))

    elif archivo.endswith(".xls"):
        shutil.move(os.join(), os.path.join(ruta, "Excel", archivo))




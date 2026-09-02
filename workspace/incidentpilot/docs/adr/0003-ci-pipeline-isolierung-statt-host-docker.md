# CI-Pipeline-Isolierung statt Host-Docker-Zugriff

Status: Angenommen

## Kontext

Das Projekt scheiterte an CI-Builds aufgrund von Versuchen, auf Windows-spezifische Docker-Pipes zuzugreifen. Die Alternative war die Nutzung von Docker-in-Docker oder Remote-Builds, was jedoch komplexer und fehleranfälliger ist.

## Entscheidung

Ausschließliche Nutzung von Linux-nativen Service-Containern in der CI-Pipeline (GitHub Actions) ohne Host-Socket-Mounting.

## Konsequenzen

Vermeidet plattformspezifische Pfadprobleme (npipe) in CI-Umgebungen. Erfordert, dass CI-Pipelines keine Host-Docker-Sockets mounten, sondern isolierte Service-Container nutzen.

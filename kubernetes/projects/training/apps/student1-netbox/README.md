# Student 1 NetBox

Endpoint https://netbox-lab1.practicelab.dev uses Cloudflare Tunnel with edge TLS. The web and worker use PostgreSQL database `netbox_student1` and Valkey indexes 14/15. Authorized operators can retrieve the bootstrap password from `student1-netbox-admin` in namespace `student1`.

The web and worker load NetBox DNS and NetBox Branching from the pinned student image.

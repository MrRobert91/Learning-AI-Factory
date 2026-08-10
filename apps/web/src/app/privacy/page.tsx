import type { Metadata } from "next";
import Link from "next/link";
import {
  BrandMark,
  IconFileText,
  IconFlask,
} from "@/components/ui";

export const metadata: Metadata = {
  title: "Política de privacidad",
  description:
    "Cómo AI Learning Factory recoge, utiliza, conserva y comparte los datos necesarios para fabricar cursos con inteligencia artificial.",
  robots: {
    index: true,
    follow: true,
  },
};

const SECTIONS = [
  ["responsable", "1. Responsable"],
  ["datos", "2. Datos que tratamos"],
  ["finalidades", "3. Para qué los usamos"],
  ["proveedores", "4. Proveedores y destinatarios"],
  ["conservacion", "5. Conservación"],
  ["seguridad", "6. Seguridad"],
  ["derechos", "7. Tus derechos"],
  ["cookies", "8. Cookies"],
  ["menores", "9. Menores y datos de terceros"],
  ["cambios", "10. Cambios en esta política"],
] as const;

const providerLinkClass =
  "font-semibold text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]";

export default function PrivacyPage() {
  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-3">
            <BrandMark size={38} />
            <span>
              <span className="block text-sm font-extrabold tracking-tight text-zinc-50">
                RustyRoboz Labs
              </span>
              <span className="block text-xs font-medium text-zinc-500">
                AI Learning Factory
              </span>
            </span>
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/terms" className="btn-secondary btn-sm">
              Condiciones del servicio
            </Link>
            <Link href="/" className="btn-secondary btn-sm">
              Ir a la aplicación
            </Link>
          </div>
        </header>

        <section className="card relative mb-8 overflow-hidden bg-[var(--paper-sheet)] p-6 sm:p-10">
          <div
            className="absolute inset-y-0 left-0 w-2 bg-[var(--rust)]"
            aria-hidden="true"
          />
          <div className="flex max-w-3xl items-start gap-4">
            <span className="mt-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-md border-2 border-[#241d18] bg-[#f2d9d2] text-[var(--rust-deep)] shadow-[3px_3px_0_0_var(--shadow)]">
              <IconFileText size={24} />
            </span>
            <div>
              <p className="mb-2 text-xs font-extrabold uppercase tracking-[0.18em] text-[var(--rust-deep)]">
                Información legal
              </p>
              <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50 sm:text-4xl">
                Política de privacidad
              </h1>
              <p className="mt-4 text-base leading-relaxed text-zinc-300">
                Esta política explica cómo se tratan los datos al utilizar AI
                Learning Factory, una plataforma que convierte ideas, fuentes y
                configuraciones en cursos y materiales educativos mediante
                agentes de inteligencia artificial.
              </p>
              <p className="mt-4 text-sm font-semibold text-zinc-500">
                Última actualización: 28 de julio de 2026
              </p>
            </div>
          </div>
        </section>

        <div className="grid items-start gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
          <nav
            aria-label="Contenido de la política"
            className="card p-5 lg:sticky lg:top-6"
          >
            <p className="mb-3 text-xs font-extrabold uppercase tracking-[0.15em] text-zinc-500">
              En esta página
            </p>
            <ol className="space-y-1">
              {SECTIONS.map(([id, label]) => (
                <li key={id}>
                  <a
                    href={`#${id}`}
                    className="block rounded px-2 py-1.5 text-sm font-semibold text-zinc-400 transition-colors hover:bg-[#f2e9d8] hover:text-[var(--rust-deep)]"
                  >
                    {label}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <article className="card notebook-sheet overflow-hidden px-6 py-8 sm:px-10 sm:py-10">
            <div className="relative space-y-10 pl-5 sm:pl-7">
              <section id="responsable" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  1. Responsable del tratamiento
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El responsable es <strong>RustyRoboz Labs</strong>, a través
                  de la persona u organización que administra la instancia de
                  AI Learning Factory a la que accedes. Para cualquier consulta
                  de privacidad o para ejercer tus derechos, utiliza el canal
                  de soporte o el contacto que te facilitó las credenciales de
                  acceso.
                </p>
                <div className="mt-5 rounded-md border-2 border-[#241d18] bg-[#f2e9d8] p-4">
                  <p className="text-sm font-semibold leading-relaxed text-zinc-300">
                    AI Learning Factory funciona como una aplicación de acceso
                    restringido. El administrador de cada instalación determina
                    dónde se aloja y qué proveedores opcionales habilita.
                  </p>
                </div>
              </section>

              <section id="datos" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  2. Datos que tratamos
                </h2>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    <strong>Cuenta y acceso:</strong> email y nombre del usuario
                    configurado por el administrador, además de una cookie de
                    sesión firmada. La contraseña introducida se comprueba para
                    autenticarte y no se guarda como contenido de usuario.
                  </li>
                  <li>
                    <strong>Contenido de trabajo:</strong> ideas, respuestas,
                    prompts, títulos, audiencias, estilos, planes, lecciones,
                    diapositivas, guiones, audios, vídeos y demás artefactos que
                    creas o generas.
                  </li>
                  <li>
                    <strong>Fuentes:</strong> archivos y URL que aportas, su
                    texto extraído, metadatos técnicos, tamaño, tipo de archivo
                    y huella digital para evitar duplicados.
                  </li>
                  <li>
                    <strong>Configuración:</strong> perfiles de agentes,
                    workflows, modelos, voces, preferencias multimedia y
                    políticas de revisión.
                  </li>
                  <li>
                    <strong>Operación y costes:</strong> estado de trabajos,
                    eventos de progreso, errores, proveedor y modelo utilizados,
                    tokens, caracteres, unidades generadas y coste real o
                    estimado. Los registros de uso no guardan prompts ni
                    respuestas.
                  </li>
                  <li>
                    <strong>YouTube, si lo conectas:</strong> credenciales OAuth,
                    identificadores de vídeos, datos de publicación y, cuando
                    solicitas análisis, métricas y comentarios del canal.
                  </li>
                  <li>
                    <strong>Datos técnicos:</strong> fecha y hora, rutas
                    solicitadas, errores y otros registros necesarios para
                    mantener y proteger el servicio. El proveedor de alojamiento
                    también puede registrar IP, navegador y dispositivo.
                  </li>
                </ul>
              </section>

              <section id="finalidades" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  3. Para qué usamos los datos
                </h2>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    Prestar las funciones de ideación, investigación, generación,
                    revisión, renderizado, exportación y publicación que
                    solicitas.
                  </li>
                  <li>
                    Mantener el historial versionado de proyectos, perfiles,
                    fuentes y artefactos, y permitir pausar o reanudar trabajos.
                  </li>
                  <li>
                    Calcular y mostrar el consumo de modelos y proveedores sin
                    guardar en esos registros el contenido de las conversaciones.
                  </li>
                  <li>
                    Autenticar el acceso, prevenir usos no autorizados,
                    diagnosticar errores y mantener la seguridad.
                  </li>
                  <li>
                    Conectar y operar YouTube únicamente cuando autorizas la
                    cuenta y confirmas una publicación o un análisis.
                  </li>
                  <li>Cumplir obligaciones legales aplicables.</li>
                </ul>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La base jurídica es la prestación del servicio solicitado y
                  el interés legítimo en mantenerlo seguro y operativo. Las
                  integraciones opcionales que requieren autorización, como
                  YouTube, se activan con tu consentimiento, que puedes retirar
                  desconectando la integración o revocando el acceso desde tu
                  cuenta del proveedor.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Los agentes generan contenido y pueden evaluarlo, pero la
                  aplicación no toma decisiones automatizadas con efectos
                  legales o equivalentes sobre personas.
                </p>
              </section>

              <section id="proveedores" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  4. Proveedores y destinatarios
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La aplicación conserva su base de datos y archivos en la
                  infraestructura elegida por el administrador. Para ejecutar
                  las funciones que solicitas puede comunicar la parte necesaria
                  del contenido a estos proveedores:
                </p>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    <a
                      className={providerLinkClass}
                      href="https://openrouter.ai/privacy/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      OpenRouter
                    </a>
                    , que enruta solicitudes a los modelos de texto, imagen o
                    voz seleccionados. El proveedor final del modelo también
                    puede tratar la entrada y la salida según sus propias
                    condiciones.
                  </li>
                  <li>
                    <a
                      className={providerLinkClass}
                      href="https://openai.com/policies/privacy-policy/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      OpenAI
                    </a>
                    , cuando el perfil de audio configurado usa directamente sus
                    servicios TTS.
                  </li>
                  <li>
                    <a
                      className={providerLinkClass}
                      href="https://www.tavily.com/privacy"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Tavily
                    </a>{" "}
                    o{" "}
                    <a
                      className={providerLinkClass}
                      href="https://duckduckgo.com/privacy"
                      target="_blank"
                      rel="noreferrer"
                    >
                      DuckDuckGo
                    </a>
                    , según la configuración, para las consultas de investigación
                    web.
                  </li>
                  <li>
                    <a
                      className={providerLinkClass}
                      href="https://policies.google.com/privacy?hl=es"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Google y YouTube
                    </a>
                    , solo si conectas la cuenta, para subir vídeos y consultar
                    datos del canal autorizados mediante OAuth.
                  </li>
                  <li>
                    Los sitios web o servidores de archivos cuya URL pides
                    capturar como fuente.
                  </li>
                </ul>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  No vendemos datos personales ni los utilizamos para publicidad
                  comportamental. Algunos proveedores pueden tratar datos fuera
                  del Espacio Económico Europeo; en ese caso se aplicarán las
                  garantías y condiciones indicadas por el proveedor y por el
                  administrador de la instancia.
                </p>
                <div className="mt-5 flex gap-3 rounded-md border-2 border-[#241d18] bg-[#f6e3df] p-4">
                  <IconFlask
                    size={20}
                    className="mt-0.5 shrink-0 text-[var(--rust-deep)]"
                  />
                  <p className="text-sm font-semibold leading-relaxed text-zinc-300">
                    Evita incluir datos personales sensibles, confidenciales o
                    de terceros en prompts y fuentes salvo que tengas autorización
                    y la configuración de proveedores sea adecuada para ese uso.
                  </p>
                </div>
              </section>

              <section id="conservacion" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  5. Conservación
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Los proyectos, fuentes, configuraciones, artefactos, trabajos y
                  registros de uso se conservan mientras la instancia siga
                  utilizándolos o hasta que el usuario o administrador los
                  elimine, salvo que deban mantenerse durante más tiempo para
                  cumplir una obligación legal, proteger la seguridad o resolver
                  una reclamación. Los tokens de YouTube se conservan mientras
                  la conexión esté activa. Cada proveedor externo aplica además
                  sus propios plazos de conservación.
                </p>
              </section>

              <section id="seguridad" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  6. Seguridad
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La aplicación limita el acceso mediante contraseña y cookie de
                  sesión firmada, separa las credenciales de proveedor del
                  contenido visible y mantiene los datos de la instancia en una
                  base de datos y un sistema de archivos controlados por el
                  administrador. También registra errores operativos para poder
                  investigarlos. Ningún sistema es completamente infalible: el
                  administrador debe mantener secretos robustos, HTTPS, copias
                  de seguridad y acceso restringido a la infraestructura.
                </p>
              </section>

              <section id="derechos" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  7. Tus derechos
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Cuando la normativa sea aplicable, puedes solicitar acceso,
                  rectificación, supresión, oposición, limitación y portabilidad
                  de tus datos, así como retirar un consentimiento sin que ello
                  afecte al tratamiento anterior. Dirige la solicitud al
                  administrador de la instancia por el canal de contacto que te
                  proporcionó, indicando el derecho que quieres ejercer y la
                  información necesaria para verificar tu identidad.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Si consideras que el tratamiento incumple la normativa, puedes
                  presentar una reclamación ante la{" "}
                  <a
                    className={providerLinkClass}
                    href="https://www.aepd.es/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Agencia Española de Protección de Datos
                  </a>{" "}
                  o ante la autoridad de control que corresponda a tu país.
                </p>
              </section>

              <section id="cookies" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  8. Cookies
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  AI Learning Factory utiliza una única cookie propia y
                  estrictamente necesaria para mantener la sesión. No incorpora
                  cookies publicitarias ni de analítica de audiencia.
                </p>
                <div className="mt-5 overflow-x-auto">
                  <table className="w-full min-w-[620px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="bg-[#f2e9d8]">
                        <th className="border-2 border-[#241d18] px-3 py-2 font-extrabold">
                          Cookie
                        </th>
                        <th className="border-2 border-[#241d18] px-3 py-2 font-extrabold">
                          Finalidad
                        </th>
                        <th className="border-2 border-[#241d18] px-3 py-2 font-extrabold">
                          Duración
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="border-2 border-[#241d18] px-3 py-3 font-mono text-xs">
                          factory_session
                        </td>
                        <td className="border-2 border-[#241d18] px-3 py-3">
                          Autenticar el acceso y mantener la sesión iniciada.
                        </td>
                        <td className="border-2 border-[#241d18] px-3 py-3">
                          Hasta 30 días o hasta cerrar sesión.
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              <section id="menores" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  9. Menores y datos de terceros
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La plataforma está dirigida a personas con acceso autorizado y
                  no solicita intencionadamente datos de menores. Si creas
                  materiales sobre alumnos, docentes u otras personas, debes
                  disponer de una base legítima para usar esa información,
                  aplicar minimización y evitar datos identificativos cuando no
                  sean necesarios.
                </p>
              </section>

              <section id="cambios" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  10. Cambios en esta política
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Esta política podrá actualizarse cuando cambien las funciones,
                  proveedores o requisitos legales de AI Learning Factory. La
                  fecha de la versión vigente aparecerá siempre al inicio. Los
                  cambios relevantes se comunicarán por un medio adecuado dentro
                  de la aplicación o a través del administrador de la instancia.
                </p>
              </section>
            </div>
          </article>
        </div>

        <footer className="mt-8 flex flex-col items-center justify-between gap-3 border-t-2 border-[#241d18] py-6 text-xs font-semibold text-zinc-500 sm:flex-row">
          <p>© 2026 RustyRoboz Labs · AI Learning Factory</p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Link
              href="/terms"
              className="text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]"
            >
              Condiciones del servicio
            </Link>
            <Link
              href="/"
              className="text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]"
            >
              Volver a la aplicación
            </Link>
          </div>
        </footer>
      </div>
    </main>
  );
}

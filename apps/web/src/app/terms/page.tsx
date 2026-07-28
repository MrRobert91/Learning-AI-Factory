import type { Metadata } from "next";
import Link from "next/link";
import { BrandMark, IconFileText, IconFlask } from "@/components/ui";

export const metadata: Metadata = {
  title: "Condiciones del servicio",
  description:
    "Condiciones de acceso y uso de AI Learning Factory y de sus funciones de generación de cursos con inteligencia artificial.",
  robots: {
    index: true,
    follow: true,
  },
};

const SECTIONS = [
  ["aceptacion", "1. Aceptación"],
  ["acceso", "2. Acceso y cuenta"],
  ["servicio", "3. Qué ofrece el servicio"],
  ["contenido", "4. Tu contenido y tus fuentes"],
  ["uso-aceptable", "5. Uso aceptable"],
  ["inteligencia-artificial", "6. Resultados de IA"],
  ["proveedores", "7. Proveedores y costes"],
  ["youtube", "8. Publicación en YouTube"],
  ["propiedad", "9. Propiedad intelectual"],
  ["disponibilidad", "10. Disponibilidad y suspensión"],
  ["responsabilidad", "11. Garantías y responsabilidad"],
  ["privacidad-cambios", "12. Privacidad, ley y cambios"],
] as const;

const externalLinkClass =
  "font-semibold text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]";

export default function TermsPage() {
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
            <Link href="/privacy" className="btn-secondary btn-sm">
              Política de privacidad
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
                Condiciones del servicio
              </h1>
              <p className="mt-4 text-base leading-relaxed text-zinc-300">
                Estas condiciones regulan el acceso y uso de AI Learning
                Factory, incluida la creación de cursos, contenidos y materiales
                multimedia mediante agentes de inteligencia artificial.
              </p>
              <p className="mt-4 text-sm font-semibold text-zinc-500">
                Última actualización: 28 de julio de 2026
              </p>
            </div>
          </div>
        </section>

        <div className="grid items-start gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
          <nav
            aria-label="Contenido de las condiciones"
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
              <section id="aceptacion" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  1. Aceptación y responsable
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Al acceder o utilizar AI Learning Factory aceptas estas
                  condiciones y la{" "}
                  <Link className={externalLinkClass} href="/privacy">
                    política de privacidad
                  </Link>
                  . Si no estás de acuerdo, no debes utilizar la aplicación.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El servicio lo proporciona <strong>RustyRoboz Labs</strong> a
                  través de la persona u organización que administra la
                  instancia a la que accedes. Ese administrador determina el
                  alojamiento, los proveedores habilitados y el canal de
                  soporte aplicable.
                </p>
              </section>

              <section id="acceso" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  2. Acceso y cuenta
                </h2>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    El acceso está restringido a personas autorizadas por el
                    administrador de la instancia.
                  </li>
                  <li>
                    Debes tener capacidad legal suficiente o autorización de la
                    organización a la que representas. Las personas menores solo
                    podrán usar el servicio bajo la autorización y supervisión
                    exigidas por la normativa aplicable.
                  </li>
                  <li>
                    Eres responsable de mantener las credenciales confidenciales,
                    cerrar sesión en dispositivos compartidos y avisar si
                    sospechas de un acceso no autorizado.
                  </li>
                  <li>
                    No puedes compartir el acceso con personas no autorizadas ni
                    intentar suplantar a otra persona u organización.
                  </li>
                </ul>
              </section>

              <section id="servicio" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  3. Qué ofrece el servicio
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  AI Learning Factory permite idear, investigar, planificar y
                  producir cursos; generar lecciones, presentaciones, imágenes,
                  guiones, voz, subtítulos y vídeo; revisar versiones; exportar
                  artefactos; y preparar o realizar publicaciones cuando lo
                  solicitas.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Algunas funciones son opcionales y dependen de claves,
                  perfiles, modelos, herramientas locales o cuentas de terceros
                  configuradas por el administrador. La disponibilidad de una
                  función en la interfaz no garantiza que su proveedor esté
                  configurado o disponible en todo momento.
                </p>
              </section>

              <section id="contenido" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  4. Tu contenido y tus fuentes
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Conservas los derechos que tengas sobre las ideas, textos,
                  archivos, imágenes, marcas y demás contenido que aportes. Al
                  introducirlo, concedes al responsable y a los proveedores
                  habilitados una licencia no exclusiva, limitada y necesaria
                  para alojarlo, procesarlo, transformarlo y generar los
                  resultados que solicitas.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Declaras que tienes los derechos, permisos y bases legales
                  necesarios para usar cada fuente y para tratar los datos
                  personales que contenga. No debes aportar secretos,
                  credenciales, información confidencial o datos especialmente
                  sensibles salvo que sea imprescindible, esté autorizado y la
                  configuración técnica sea adecuada.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Eres responsable de revisar licencias, citas, atribuciones y
                  restricciones de los documentos y sitios web utilizados como
                  fuentes, incluso cuando la aplicación facilite su extracción
                  o resumen.
                </p>
              </section>

              <section id="uso-aceptable" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  5. Uso aceptable
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  No puedes utilizar el servicio para:
                </p>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    Infringir leyes, derechos de autor, marcas, privacidad u
                    otros derechos de terceros.
                  </li>
                  <li>
                    Crear o distribuir contenido fraudulento, difamatorio,
                    abusivo, discriminatorio, sexualmente explotador o que
                    facilite daño, violencia o actividades ilegales.
                  </li>
                  <li>
                    Generar malware, explotar vulnerabilidades, eludir controles
                    de seguridad o acceder a sistemas y datos sin autorización.
                  </li>
                  <li>
                    Automatizar decisiones de alto impacto sobre personas en
                    ámbitos como empleo, crédito, salud, educación, vivienda o
                    justicia sin una base legal, supervisión humana y garantías
                    adecuadas.
                  </li>
                  <li>
                    Saturar la infraestructura, abusar de cuotas o intentar
                    extraer, copiar o revender el servicio o las credenciales de
                    sus proveedores.
                  </li>
                  <li>
                    Presentar contenido sintético como auténtico cuando pueda
                    inducir a error o causar perjuicios.
                  </li>
                </ul>
              </section>

              <section id="inteligencia-artificial" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  6. Resultados de inteligencia artificial
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Los agentes y modelos pueden producir información inexacta,
                  incompleta, desactualizada, sesgada o similar a contenidos
                  existentes. Los controles automáticos y las citas reducen
                  riesgos, pero no sustituyen una revisión humana competente.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Antes de publicar o utilizar un artefacto debes comprobar,
                  según el contexto, los hechos, cálculos, código, citas,
                  licencias, accesibilidad, seguridad, adecuación pedagógica y
                  derechos de terceros. Los resultados no constituyen
                  asesoramiento médico, jurídico, financiero ni profesional y no
                  deben ser la única base para decisiones relevantes.
                </p>
                <div className="mt-5 flex gap-3 rounded-md border-2 border-[#241d18] bg-[#f6e3df] p-4">
                  <IconFlask
                    size={20}
                    className="mt-0.5 shrink-0 text-[var(--rust-deep)]"
                  />
                  <p className="text-sm font-semibold leading-relaxed text-zinc-300">
                    La revisión, aprobación y publicación final corresponden al
                    usuario. Activa revisión humana en los perfiles cuando el
                    riesgo o el destino del material lo requieran.
                  </p>
                </div>
              </section>

              <section id="proveedores" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  7. Proveedores, modelos y costes
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El servicio puede depender de OpenRouter y de los proveedores
                  de sus modelos, OpenAI, Tavily, DuckDuckGo, Google/YouTube y de
                  la infraestructura de alojamiento. Tu uso de esas funciones
                  también está sujeto a sus condiciones vigentes:
                </p>
                <ul className="mt-4 list-disc space-y-3 pl-6 leading-relaxed text-zinc-300 marker:text-[var(--rust)]">
                  <li>
                    <a
                      className={externalLinkClass}
                      href="https://openrouter.ai/terms"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Condiciones de OpenRouter
                    </a>{" "}
                    y las condiciones del modelo elegido.
                  </li>
                  <li>
                    <a
                      className={externalLinkClass}
                      href="https://openai.com/policies/service-terms/"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Condiciones de servicio de OpenAI
                    </a>
                    , cuando se utilicen sus servicios.
                  </li>
                  <li>
                    <a
                      className={externalLinkClass}
                      href="https://www.tavily.com/terms"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Condiciones de Tavily
                    </a>{" "}
                    y{" "}
                    <a
                      className={externalLinkClass}
                      href="https://duckduckgo.com/terms"
                      target="_blank"
                      rel="noreferrer"
                    >
                      condiciones de DuckDuckGo
                    </a>
                    , según el motor de investigación configurado.
                  </li>
                  <li>
                    <a
                      className={externalLinkClass}
                      href="https://developers.google.com/terms"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Condiciones de las API de Google
                    </a>{" "}
                    y{" "}
                    <a
                      className={externalLinkClass}
                      href="https://www.youtube.com/t/terms"
                      target="_blank"
                      rel="noreferrer"
                    >
                      condiciones de YouTube
                    </a>
                    , si conectas el canal.
                  </li>
                </ul>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Los modelos, precios, límites, políticas y prestaciones pueden
                  cambiar o dejar de estar disponibles. Los registros de uso y
                  estimaciones de coste son informativos; la facturación
                  definitiva corresponde al proveedor y al titular de sus claves
                  o cuentas.
                </p>
              </section>

              <section id="youtube" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  8. Publicación y análisis de YouTube
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La conexión con YouTube es opcional y requiere autorización
                  OAuth. Una subida solo comienza tras una acción y confirmación
                  explícitas del usuario. Eres responsable del canal, de la
                  privacidad seleccionada, del contenido y metadatos publicados,
                  de las autorizaciones de imagen y voz, y del cumplimiento de
                  las políticas de YouTube.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Si solicitas mejora continua, la aplicación puede consultar
                  métricas y comentarios autorizados para generar propuestas.
                  Esas propuestas no se aplican automáticamente y deben ser
                  revisadas por una persona.
                </p>
              </section>

              <section id="propiedad" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  9. Propiedad intelectual
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La aplicación, su diseño, marca, documentación y componentes
                  pertenecen a sus respectivos titulares y están protegidos por
                  la normativa aplicable. Estas condiciones no te conceden
                  derechos sobre la marca RustyRoboz Labs ni sobre componentes de
                  terceros.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  La titularidad y los derechos de uso sobre resultados generados
                  pueden depender del contenido aportado, del modelo utilizado,
                  de sus condiciones y de la legislación aplicable. Eres
                  responsable de comprobar que el uso o comercialización
                  previstos estén permitidos.
                </p>
              </section>

              <section id="disponibilidad" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  10. Disponibilidad, cambios y suspensión
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El servicio puede cambiar, añadir o retirar funciones, modelos
                  y proveedores, o interrumpirse por mantenimiento, fallos,
                  límites de cuota o causas externas. Cuando sea razonable, los
                  cambios relevantes se comunicarán dentro de la aplicación o a
                  través del administrador.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El administrador puede limitar o suspender el acceso para
                  proteger la seguridad, cumplir la ley, evitar daños o responder
                  a un incumplimiento de estas condiciones o de las políticas de
                  un proveedor. Al finalizar el acceso, solicita al administrador
                  la exportación o eliminación que proceda antes de que los datos
                  dejen de estar disponibles.
                </p>
              </section>

              <section id="responsabilidad" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  11. Garantías y responsabilidad
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  En la medida permitida por la ley, el servicio se ofrece tal
                  cual y según disponibilidad, sin garantía de funcionamiento
                  ininterrumpido ni de que los resultados sean exactos, completos,
                  originales o adecuados para un fin concreto.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El responsable no responde de decisiones tomadas sin revisión,
                  publicaciones no autorizadas, infracciones derivadas del
                  contenido aportado, cambios de proveedores o pérdidas
                  indirectas que no le sean legalmente imputables. Nada de lo
                  anterior excluye responsabilidades que no puedan limitarse por
                  ley ni los derechos imperativos de consumidores y usuarios.
                </p>
              </section>

              <section id="privacidad-cambios" className="scroll-mt-8">
                <h2 className="text-2xl font-extrabold tracking-tight text-zinc-50">
                  12. Privacidad, ley aplicable y cambios
                </h2>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  El tratamiento de datos se describe en la{" "}
                  <Link className={externalLinkClass} href="/privacy">
                    política de privacidad
                  </Link>
                  , que forma parte de estas condiciones.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Se aplicará la ley del lugar donde esté establecido el
                  responsable que opera la instancia y serán competentes los
                  tribunales que determine esa normativa, sin perjuicio de las
                  protecciones imperativas que correspondan al usuario.
                </p>
                <p className="mt-4 leading-relaxed text-zinc-300">
                  Estas condiciones podrán actualizarse para reflejar cambios
                  funcionales, de proveedores o legales. La fecha vigente se
                  mostrará al inicio. Si un cambio altera de forma relevante tus
                  derechos u obligaciones, se comunicará por un medio adecuado.
                  Para consultas, reclamaciones o solicitudes utiliza el canal de
                  soporte que te facilitó el administrador de la instancia.
                </p>
              </section>
            </div>
          </article>
        </div>

        <footer className="mt-8 flex flex-col items-center justify-between gap-3 border-t-2 border-[#241d18] py-6 text-xs font-semibold text-zinc-500 sm:flex-row">
          <p>© 2026 RustyRoboz Labs · AI Learning Factory</p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Link
              href="/privacy"
              className="text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]"
            >
              Política de privacidad
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

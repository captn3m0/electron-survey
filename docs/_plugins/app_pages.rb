# Generate one page per app from site.data.apps (symlinked from data/apps/),
# rendered with the `app` layout. Requires a non-safe build
# (`bundle exec jekyll build`).
module ElectronSurvey
  class AppPageGenerator < Jekyll::Generator
    safe false
    priority :low

    def generate(site)
      apps = site.data["apps"] || {}
      scores = (site.data["popularity"] || {})["scores"] || {}
      apps.each do |id, app|
        next unless app.is_a?(Hash)
        site.pages << AppPage.new(site, id.to_s, app, scores[id.to_s])
      end
    end
  end

  class AppPage < Jekyll::Page
    def initialize(site, id, app, score)
      @site = site
      @base = site.source
      @dir  = "apps"
      @name = "#{id}.html"
      process(@name)
      self.content = ""
      self.data = {
        "layout" => "app",
        "title"  => (app["name"] || id),
        "app_id" => id,
        "app"    => app,
        "score"  => score,
      }
    end
  end
end

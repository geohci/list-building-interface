# list-building-interface
Toolforge interface to allow users to explore various list-building approaches. 

UI based on the following template: https://github.com/wikimedia/research-api-interface-template

## License
The source code for this interface is released under the [MIT license](https://github.com/geohci/wikidata-topic-model-api/blob/master/LICENSE).

Screenshots of the results in the API may be used without attribution, but a link back to the application would be appreciated.

## Developing
It's easiest to work from a local repository. To test out the app, navigate to the repo and start flask:
* `$ flask run` (or in development mode -- e.g., `$ FLASK_ENV=development flask run --extra-files file1:static/style.css`) and navigate to the localhost link provided in command-line
* You might have to disable cross-site restrictions if the API calls aren't working (in Safari, this is `Disable Cross-Origin Restrictions` under the `Develop` menu)

## Updating the App
Though it's possible to setup webhooks so the tool updates automatically with changes to Github, this in practice is risky and manually updating the tool is not particularly difficult.
See [this documentation](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Web#Using_the_webservice_command), but in practice, updating the tool is just a few simple steps:
* login to toolforge (`$ ssh login.toolforge.org`)
* become the tool (`$ become list-building`)
* navigate to tool directory (`$ cd www/python/src/`)
* pull in new changes (`$ git pull`)
* restart the webservice (`$ webservice restart`)